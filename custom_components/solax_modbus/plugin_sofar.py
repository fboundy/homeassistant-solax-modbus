import logging
from dataclasses import dataclass
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.button import ButtonEntityDescription
from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder, Endian
from custom_components.solax_modbus.const import *

_LOGGER = logging.getLogger(__name__)

""" ============================================================================================
bitmasks  definitions to characterize inverters, ogranized by group
these bitmasks are used in entitydeclarations to determine to which inverters the entity applies
within a group, the bits in an entitydeclaration will be interpreted as OR
between groups, an AND condition is applied, so all gruoups must match.
An empty group (group without active flags) evaluates to True.
example: GEN3 | GEN4 | X1 | X3 | EPS 
means:  any inverter of tyoe (GEN3 or GEN4) and (X1 or X3) and (EPS)
An entity can be declared multiple times (with different bitmasks) if the parameters are different for each inverter type
"""

GEN            = 0x0001 # base generation for MIC, PV, AC
GEN2           = 0x0002
GEN3           = 0x0004
GEN4           = 0x0008
ALL_GEN_GROUP  = GEN2 | GEN3 | GEN4 | GEN

X1             = 0x0100
X3             = 0x0200
ALL_X_GROUP    = X1 | X3

PV             = 0x0400 # Needs further work on PV Only Inverters
AC             = 0x0800
HYBRID         = 0x1000
MIC            = 0x2000
ALL_TYPE_GROUP = PV | AC | HYBRID | MIC

EPS            = 0x8000
ALL_EPS_GROUP  = EPS

DCB            = 0x10000 # dry contact box - gen4
ALL_DCB_GROUP  = DCB

PM  = 0x20000
ALL_PM_GROUP = PM


ALLDEFAULT = 0 # should be equivalent to HYBRID | AC | GEN2 | GEN3 | GEN4 | X1 | X3 


def matchInverterWithMask (inverterspec, entitymask, serialnumber = 'not relevant', blacklist = None):
    # returns true if the entity needs to be created for an inverter
    genmatch = ((inverterspec & entitymask & ALL_GEN_GROUP)  != 0) or (entitymask & ALL_GEN_GROUP  == 0)
    xmatch   = ((inverterspec & entitymask & ALL_X_GROUP)    != 0) or (entitymask & ALL_X_GROUP    == 0)
    hybmatch = ((inverterspec & entitymask & ALL_TYPE_GROUP) != 0) or (entitymask & ALL_TYPE_GROUP == 0)
    epsmatch = ((inverterspec & entitymask & ALL_EPS_GROUP)  != 0) or (entitymask & ALL_EPS_GROUP  == 0)
    dcbmatch = ((inverterspec & entitymask & ALL_DCB_GROUP)  != 0) or (entitymask & ALL_DCB_GROUP  == 0)
    pmmatch = ((inverterspec & entitymask & ALL_PM_GROUP)  != 0) or (entitymask & ALL_PM_GROUP  == 0)
    blacklisted = False
    if blacklist:
        for start in blacklist: 
            if serialnumber.startswith(start) : blacklisted = True
    return (genmatch and xmatch and hybmatch and epsmatch and dcbmatch and pmmatch) and not blacklisted

# ======================= end of bitmask handling code =============================================

# ====================== find inverter type and details ===========================================

def _read_serialnr(hub, address, swapbytes):
    res = None
    try:
        inverter_data = hub.read_holding_registers(unit=hub._modbus_addr, address=address, count=7)
        if not inverter_data.isError(): 
            decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.Big)
            res = decoder.decode_string(14).decode("ascii")
            if swapbytes: 
                ba = bytearray(res,"ascii") # convert to bytearray for swapping
                ba[0::2], ba[1::2] = ba[1::2], ba[0::2] # swap bytes ourselves - due to bug in Endian.Little ?
                res = str(ba, "ascii") # convert back to string
            hub.seriesnumber = res    
    except Exception as ex: _LOGGER.warning(f"{hub.name}: attempt to read serialnumber failed at 0x{address:x}", exc_info=True)
    if not res: _LOGGER.warning(f"{hub.name}: reading serial number from address 0x{address:x} failed; other address may succeed")
    _LOGGER.info(f"Read {hub.name} 0x{address:x} serial number: {res}, swapped: {swapbytes}")
    #return 'SP1ES2' 
    return res

def determineInverterType(hub, configdict):
    _LOGGER.info(f"{hub.name}: trying to determine inverter type")
    seriesnumber                       = _read_serialnr(hub, 0x445,  swapbytes = False)
    if not seriesnumber:  seriesnumber = _read_serialnr(hub, 0x2001, swapbytes = False) # Need modify _read_serialnr to also input registers
    if not seriesnumber: 
        _LOGGER.error(f"{hub.name}: cannot find serial number, even not for other Inverter")
        seriesnumber = "unknown"

    # derive invertertype from seriiesnumber
    if   seriesnumber.startswith('SP1ES120N6'):  invertertype = HYBRID | X3 # HYD20KTL-3P no PV
    elif seriesnumber.startswith('SP1'):  invertertype = HYBRID | X3 | GEN # HYDxxKTL-3P
    elif seriesnumber.startswith('SP2'):  invertertype = HYBRID | X3 | GEN # HYDxxKTL-3P 2nd type
    elif seriesnumber.startswith('SM1E'):  invertertype = HYBRID | X3 | GEN # HYDxxxxES, Not actually X3, needs changing
    elif seriesnumber.startswith('ZM1E'):  invertertype = HYBRID | X3 | GEN # HYDxxxxES 2nd type, Not actually X3, needs changing
    elif seriesnumber.startswith('SS2E'):  invertertype = PV | X3 | GEN # 4.4 KTLX-G3
    elif seriesnumber.startswith('SA1'):  invertertype = PV | X1 # Older Might be single
    elif seriesnumber.startswith('SB1'):  invertertype = PV | X1 # Older Might be single
    elif seriesnumber.startswith('SC1'):  invertertype = PV | X3 # Older Probably 3phase
    elif seriesnumber.startswith('SD1'):  invertertype = PV | X3 # Older Probably 3phase
    elif seriesnumber.startswith('SF4'):  invertertype = PV | X3 # Older Probably 3phase
    elif seriesnumber.startswith('SH1'):  invertertype = PV | X3 # Older Probably 3phase
    elif seriesnumber.startswith('SL1'):  invertertype = PV | X3 # Older Probably 3phase
    elif seriesnumber.startswith('SJ2'):  invertertype = PV | X3 # Older Probably 3phase

    else: 
        invertertype = 0
        _LOGGER.error(f"unrecognized {hub.name} inverter type - serial number : {seriesnumber}")
    read_eps = configdict.get(CONF_READ_EPS, DEFAULT_READ_EPS)
    read_dcb = configdict.get(CONF_READ_DCB, DEFAULT_READ_DCB)
    read_pm = configdict.get(CONF_READ_PM, DEFAULT_READ_PM)
    if read_eps: invertertype = invertertype | EPS 
    if read_dcb: invertertype = invertertype | DCB
    if read_pm: invertertype = invertertype | PM
    hub.invertertype = invertertype

@dataclass
class SofarModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice

@dataclass
class SofarModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice

@dataclass
class SofarModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice

@dataclass
class SofarModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    """A class that describes Sofar Modbus sensor entities."""
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice
    order16: int = Endian.Big
    order32: int = Endian.Big
    unit: int = REGISTER_U16
    register_type: int= REG_HOLDING

# ================================= Computed sensor value functions  =================================================

def value_function_pv_total_power(initval, descr, datadict):
    return  datadict.get('pv_power_1', 0) + datadict.get('pv_power_2',0)

def value_function_grid_import(initval, descr, datadict):
    val = datadict["feedin_power"]
    if val<0: return abs(val)
    else: return 0

def value_function_grid_export(initval, descr, datadict):
    val = datadict["feedin_power"]
    if val>0: return val
    else: return 0

def value_function_house_load(initval, descr, datadict):
    return datadict['inverter_load'] - datadict['feedin_power']

def value_function_rtc(initval, descr, datadict):
    (rtc_seconds, rtc_minutes, rtc_hours, rtc_days, rtc_months, rtc_years, ) = initval
    val = f"{rtc_days:02}/{rtc_months:02}/{rtc_years:02} {rtc_hours:02}:{rtc_minutes:02}:{rtc_seconds:02}"
    return datetime.strptime(val, '%d/%m/%y %H:%M:%S')

def value_function_gen4time(initval, descr, datadict):
    h = initval % 256
    m = initval >> 8
    return f"{h:02d}:{m:02d}"

def value_function_gen23time(initval, descr, datadict):
    (h,m,) = initval
    return f"{h:02d}:{m:02d}"

# ================================= Button Declarations ============================================================

BUTTON_TYPES = []

SENSOR_TYPES: list[SofarModbusSensorEntityDescription] = [ 

###
#
# Real-time Data Area
#
###
    SofarModbusSensorEntityDescription(
        name="Heatsink Temperature 1",
        key="heatsink_temperature_1",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class = SensorDeviceClass.TEMPERATURE,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x41A,
        newblock = True,
        unit = REGISTER_S16,
        allowedtypes = HYBRID,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Heatsink Temperature 2",
        key="heatsink_temperature_2",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class = SensorDeviceClass.TEMPERATURE,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x41B,
        unit = REGISTER_S16,
        allowedtypes = HYBRID | PV,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Module Temperature 1",
        key="module_temperature_1",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class = SensorDeviceClass.TEMPERATURE,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x420,
        unit = REGISTER_S16,
        allowedtypes = HYBRID | PV,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Module Temperature 2",
        key="module_temperature_2",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class = SensorDeviceClass.TEMPERATURE,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x421,
        unit = REGISTER_S16,
        allowedtypes = HYBRID | PV,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name = "Serial Number",
        key = "serial_number",
        register = 0x445,
        newblock = True,
        unit=REGISTER_STR,
        wordcount=7,
        allowedtypes = HYBRID | PV,
    ),
###
#
# On Grid Output
#
###
    SofarModbusSensorEntityDescription(
        name = "Grid Frequency",
        key = "grid_frequency",
        native_unit_of_measurement = FREQUENCY_HERTZ,
        device_class = SensorDeviceClass.FREQUENCY,
        register = 0x484,
        newblock = True,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Active Power Output Total",
        key = "active_power_output_total",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x485,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Reactive Power Output Total",
        key = "reactive Power_output_total",
        native_unit_of_measurement = POWER_VOLT_AMPERE_REACTIVE,
        device_class = SensorDeviceClass.REACTIVE_POWER,
        register = 0x486,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Apparent Power Output Total",
        key = "apparent_power_output_total",
        native_unit_of_measurement = POWER_VOLT_AMPERE,
        device_class = SensorDeviceClass.APPARENT_POWER,
        register = 0x487,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Active Power PCC Total",
        key = "active_power_pcc_total",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x488,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Reactive Power PCC Total",
        key = "reactive Power_pcc_total",
        native_unit_of_measurement = POWER_VOLT_AMPERE_REACTIVE,
        device_class = SensorDeviceClass.REACTIVE_POWER,
        register = 0x489,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Apparent Power PCC Total",
        key = "apparent_power_pcc_total",
        native_unit_of_measurement = POWER_VOLT_AMPERE,
        device_class = SensorDeviceClass.APPARENT_POWER,
        register = 0x48A,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Voltage L1",
        key = "voltage_l1",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x48D,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current Output L1",
        key="current_output_l1",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x48E,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Active Power Output L1",
        key = "active_power_output_l1",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x48F,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Reactive Power Output L1",
        key = "reactive Power_output_l1",
        native_unit_of_measurement = POWER_VOLT_AMPERE_REACTIVE,
        device_class = SensorDeviceClass.REACTIVE_POWER,
        register = 0x490,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Power Factor Output L1",
        key = "power_factor_output_l1",
        device_class = SensorDeviceClass.POWER_FACTOR,
        register = 0x491,
        unit = REGISTER_S16,
        scale = 0.001,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current PCC L1",
        key="current_pcc_l1",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x492,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Active Power PCC L1",
        key = "active_power_pcc_l1",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x493,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Reactive Power PCC L1",
        key = "reactive Power_pcc_l1",
        native_unit_of_measurement = POWER_VOLT_AMPERE_REACTIVE,
        device_class = SensorDeviceClass.REACTIVE_POWER,
        register = 0x494,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Power Factor PCC L1",
        key = "power_factor_pcc_l1",
        device_class = SensorDeviceClass.POWER_FACTOR,
        register = 0x495,
        unit = REGISTER_S16,
        scale = 0.001,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Voltage L2",
        key = "voltage_l2",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x498,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current Output L2",
        key="current_output_l2",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x499,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Active Power Output L2",
        key = "active_power_output_l2",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x49A,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Reactive Power Output L2",
        key = "reactive Power_output_l2",
        native_unit_of_measurement = POWER_VOLT_AMPERE_REACTIVE,
        device_class = SensorDeviceClass.REACTIVE_POWER,
        register = 0x49B,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Power Factor Output L2",
        key = "power_factor_output_l2",
        device_class = SensorDeviceClass.POWER_FACTOR,
        register = 0x49C,
        unit = REGISTER_S16,
        scale = 0.001,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current PCC L2",
        key="current_pcc_l2",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x49D,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Active Power PCC L2",
        key = "active_power_pcc_l2",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x49E,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Reactive Power PCC L2",
        key = "reactive Power_pcc_l2",
        native_unit_of_measurement = POWER_VOLT_AMPERE_REACTIVE,
        device_class = SensorDeviceClass.REACTIVE_POWER,
        register = 0x49F,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Power Factor PCC L2",
        key = "power_factor_pcc_l2",
        device_class = SensorDeviceClass.POWER_FACTOR,
        register = 0x4A0,
        unit = REGISTER_S16,
        scale = 0.001,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Voltage L3",
        key = "voltage_l3",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x4A3,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current Output L3",
        key="current_output_l3",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x4A4,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Active Power Output L3",
        key = "active_power_output_l3",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x4A5,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Reactive Power Output L3",
        key = "reactive Power_output_l3",
        native_unit_of_measurement = POWER_VOLT_AMPERE_REACTIVE,
        device_class = SensorDeviceClass.REACTIVE_POWER,
        register = 0x4A6,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Power Factor Output L3",
        key = "power_factor_output_l3",
        device_class = SensorDeviceClass.POWER_FACTOR,
        register = 0x4A7,
        unit = REGISTER_S16,
        scale = 0.001,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current PCC L3",
        key="current_pcc_l3",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x4A8,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Active Power PCC L3",
        key = "active_power_pcc_l3",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x4A9,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Reactive Power PCC L3",
        key = "reactive Power_pcc_l3",
        native_unit_of_measurement = POWER_VOLT_AMPERE_REACTIVE,
        device_class = SensorDeviceClass.REACTIVE_POWER,
        register = 0x4AA,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Power Factor PCC L3",
        key = "power_factor_pcc_l3",
        device_class = SensorDeviceClass.POWER_FACTOR,
        register = 0x4AB,
        unit = REGISTER_S16,
        scale = 0.001,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Active Power PV Ext",
        key = "active_power_pv_ext",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x4AE,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Active Power Load Sys",
        key = "active_power_load_sys",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x4AF,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Voltage Phase L1N",
        key = "voltage_phase_l1n",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x4B0,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current Output L1N",
        key="current_output_l1n",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x4B1,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Active Power Output L1N",
        key = "active_power_output_l1n",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x4B2,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current PCC L1N",
        key="current_pcc_l1n",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x4B3,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Active Power PCC L1N",
        key = "active_power_pcc_l1n",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x4B4,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Voltage Phase L2N",
        key = "voltage_phase_l2n",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x4B5,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current Output L2N",
        key="current_output_l2n",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x4B6,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Active Power Output L2N",
        key = "active_power_output_l2n",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x4B7,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current PCC L2N",
        key="current_pcc_l2n",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x4B8,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Active Power PCC L2N",
        key = "active_power_pcc_l2n",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x4B9,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Voltage Line L1",
        key = "voltage_line_l1",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x4BA,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Voltage Line L2",
        key = "voltage_line_l2",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x4BB,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name = "Voltage Line L3",
        key = "voltage_line_l3",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x4BC,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | PV,
    ),

###
#
# Off Grid Output (0x0500-0x057F)
#
###
    SofarModbusSensorEntityDescription(
        name = "Active Power Off-Grid Total",
        key = "active_power_offgrid_total",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x504,
        #newblock = True,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Reactive Power Off-Grid Total",
        key = "reactive Power_offgrid_total",
        native_unit_of_measurement = POWER_VOLT_AMPERE_REACTIVE,
        device_class = SensorDeviceClass.REACTIVE_POWER,
        register = 0x505,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Apparent Power Off-Grid Total",
        key = "apparent_power_offgrid_total",
        native_unit_of_measurement = POWER_VOLT_AMPERE,
        device_class = SensorDeviceClass.APPARENT_POWER,
        register = 0x506,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Frequency",
        key = "offgrid_frequency",
        native_unit_of_measurement = FREQUENCY_HERTZ,
        device_class = SensorDeviceClass.FREQUENCY,
        register = 0x507,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Voltage L1",
        key = "offgrid_voltage_l1",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x50A,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Current Output L1",
        key="offgrid_current_output_l1",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x50B,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Active Power Output L1",
        key = "offgrid_active_power_output_l1",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x50C,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Reactive Power Output L1",
        key = "offgrid_reactive Power_output_l1",
        native_unit_of_measurement = POWER_VOLT_AMPERE_REACTIVE,
        device_class = SensorDeviceClass.REACTIVE_POWER,
        register = 0x50D,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Apparent Power Output L1",
        key = "offgrid_apparent_power_output_l1",
        native_unit_of_measurement=POWER_VOLT_AMPERE,
        device_class = SensorDeviceClass.APPARENT_POWER,
        register = 0x50E,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid LoadPeakRatio L1",
        key = "offgrid_loadpeakratio_l1",
        native_unit_of_measurement=POWER_VOLT_AMPERE,
        device_class = SensorDeviceClass.POWER,
        register = 0x50F,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Voltage L2",
        key = "offgrid_voltage_l2",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x512,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Current Output L2",
        key="offgrid_current_output_l2",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x513,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Active Power Output L2",
        key = "offgrid_active_power_output_l2",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x514,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Reactive Power Output L2",
        key = "offgrid_reactive Power_output_l2",
        native_unit_of_measurement = POWER_VOLT_AMPERE_REACTIVE,
        device_class = SensorDeviceClass.REACTIVE_POWER,
        register = 0x515,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Apparent Power Output L2",
        key = "offgrid_apparent_power_output_l2",
        native_unit_of_measurement=POWER_VOLT_AMPERE,
        device_class = SensorDeviceClass.APPARENT_POWER,
        register = 0x516,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid LoadPeakRatio L2",
        key = "offgrid_loadpeakratio_l2",
        native_unit_of_measurement=POWER_VOLT_AMPERE,
        device_class = SensorDeviceClass.POWER,
        register = 0x517,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Voltage L3",
        key = "offgrid_voltage_l3",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x51A,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Current Output L3",
        key="offgrid_current_output_l3",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x51B,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Active Power Output L3",
        key = "offgrid_active_power_output_l3",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x51C,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Reactive Power Output L3",
        key = "offgrid_reactive Power_output_l3",
        native_unit_of_measurement = POWER_VOLT_AMPERE_REACTIVE,
        device_class = SensorDeviceClass.REACTIVE_POWER,
        register = 0x51D,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Apparent Power Output L3",
        key = "offgrid_apparent_power_output_l3",
        native_unit_of_measurement=POWER_VOLT_AMPERE,
        device_class = SensorDeviceClass.APPARENT_POWER,
        register = 0x51E,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid LoadPeakRatio L3",
        key = "offgrid_loadpeakratio_l3",
        native_unit_of_measurement=POWER_VOLT_AMPERE,
        device_class = SensorDeviceClass.POWER,
        register = 0x51F,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Voltage Output L1N",
        key = "offgrid_voltage_output_l1n",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x522,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Current Output L1N",
        key="offgrid_current_output_l1n",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x523,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Active Power Output L1N",
        key = "offgrid_active_power_output_l1n",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x524,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Voltage Output L2N",
        key = "offgrid_voltage_output_l2n",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x525,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Current Output L2N",
        key="offgrid_current_output_l2n",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x526,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Off-Grid Active Power Output L2N",
        key = "offgrid_active_power_output_l2n",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x527,
        newblock = True,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | X3 | EPS,
    ),
###
#
# PV Input (0x0580-0x05FF)
#
###
    SofarModbusSensorEntityDescription(
        name = "PV Voltage 1",
        key = "pv_voltage_1",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x584,
        newblock = True,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "PV Current 1",
        key = "pv_current_1",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x585,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "PV Power 1",
        key = "pv_power_1",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x586,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "PV Voltage 2",
        key = "pv_voltage_2",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x587,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "PV Current 2",
        key = "pv_current_2",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x588,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "PV Power 2",
        key = "pv_power_2",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x589,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "PV Voltage 3",
        key = "pv_voltage_3",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x58A,
        scale = 0.1,
        rounding = 1,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "PV Current 3",
        key = "pv_current_3",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x58B,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "PV Power 3",
        key = "pv_power_3",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x58C,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "PV Voltage 4",
        key = "pv_voltage_4",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x58D,
        scale = 0.1,
        rounding = 1,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "PV Current 4",
        key = "pv_current_4",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x58E,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "PV Power 4",
        key = "pv_power_4",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x58F,
        newblock = True,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "PV Total Power",
        key = "pv_total_power",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x5C4,
        newblock = True,
        scale = 0.01,
        rounding = 2,
        #entity_registry_enabled_default=False,
        allowedtypes = HYBRID | PV | GEN,
    ),
###
#
# Battery Input (0x0600-0x067F)
#
###
    SofarModbusSensorEntityDescription(
        name = "Battery Voltage 1",
        key = "battery_voltage_1",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x604,
        newblock = True,
        scale = 0.1,
        rounding = 1,
        #entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name = "Battery Current 1",
        key = "battery_current_1",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x605,
        newblock = True,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        #entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name = "Battery Power 1",
        key = "Battery_power_1",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x606,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        #entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Temperature 1",
        key="battery_temperature_1",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class = SensorDeviceClass.TEMPERATURE,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x607,
        unit = REGISTER_S16,
        #entity_registry_enabled_default=False,
        allowedtypes = HYBRID | GEN,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Capacity 1",
        key="battery_capacity_charge_1",
        native_unit_of_measurement=PERCENTAGE,
        device_class = SensorDeviceClass.BATTERY,
        register = 0x608,
        #entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery State of Health 1",
        key="battery_state_of_health_1",
        register = 0x609,
        native_unit_of_measurement=PERCENTAGE,
       # entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
        icon="mdi:battery-heart",
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Charge Cycle 1",
        key="battery_charge_cycle_1",
        register = 0x60A,
        #entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name = "Battery Voltage 2",
        key = "battery_voltage_2",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x60B,
        scale = 0.1,
        rounding = 1,
        #entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name = "Battery Current 2",
        key = "battery_current_2",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x60C,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        #entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name = "Battery Power 2",
        key = "Battery_power_2",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x60D,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        #entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Temperature 2",
        key="battery_temperature_2",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class = SensorDeviceClass.TEMPERATURE,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x60E,
        unit = REGISTER_S16,
        #entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Capacity 2",
        key="battery_capacity_charge_2",
        native_unit_of_measurement=PERCENTAGE,
        device_class = SensorDeviceClass.BATTERY,
        register = 0x60F,
        #entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery State of Health 2",
        key="battery_state_of_health_2",
        register = 0x610,
        native_unit_of_measurement=PERCENTAGE,
        #entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
        icon="mdi:battery-heart",
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Charge Cycle 2",
        key="battery_charge_cycle_2",
        register = 0x611,
        #entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name = "Battery Voltage 3",
        key = "battery_voltage_3",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x612,
        scale = 0.1,
        rounding = 1,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "Battery Current 3",
        key = "battery_current_3",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x613,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "Battery Power 3",
        key = "Battery_power_3",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x614,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Temperature 3",
        key="battery_temperature_3",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class = SensorDeviceClass.TEMPERATURE,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x615,
        unit = REGISTER_S16,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | GEN,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Capacity 3",
        key="battery_capacity_charge_3",
        native_unit_of_measurement=PERCENTAGE,
        device_class = SensorDeviceClass.BATTERY,
        register = 0x616,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery State of Health 3",
        key="battery_state_of_health_3",
        register = 0x617,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | GEN,
        icon="mdi:battery-heart",
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Charge Cycle 3",
        key="battery_charge_cycle_3",
        register = 0x618,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | GEN,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name = "Battery Voltage 4",
        key = "battery_voltage_4",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x619,
        scale = 0.1,
        rounding = 1,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "Battery Current 4",
        key = "battery_current_4",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x61A,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name = "Battery Power 4",
        key = "Battery_power_4",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x61B,
        unit = REGISTER_S16,
        scale = 0.01,
        rounding = 2,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Temperature 4",
        key="battery_temperature_4",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class = SensorDeviceClass.TEMPERATURE,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x61C,
        unit = REGISTER_S16,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | GEN,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Capacity 4",
        key="battery_capacity_charge_4",
        native_unit_of_measurement=PERCENTAGE,
        device_class = SensorDeviceClass.BATTERY,
        register = 0x61D,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery State of Health 4",
        key="battery_state_of_health_4",
        register = 0x61E,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | GEN,
        icon="mdi:battery-heart",
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Charge Cycle 4",
        key="battery_charge_cycle_4",
        register = 0x61F,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | GEN,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name = "Battery Power Total",
        key = "battery_power_total",
        native_unit_of_measurement = POWER_KILO_WATT,
        device_class = SensorDeviceClass.POWER,
        register = 0x667,
        newblock = True,
        unit = REGISTER_S16,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Capacity Total",
        key="battery_capacity_charge_total",
        native_unit_of_measurement=PERCENTAGE,
        device_class = SensorDeviceClass.BATTERY,
        register = 0x668,
        allowedtypes = HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery State of Health Total",
        key="battery_state_of_health_total",
        register = 0x669,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes = HYBRID,
        icon="mdi:battery-heart",
        entity_category = EntityCategory.DIAGNOSTIC,
    ),

###
#
# Electric Power (0x0680-0x06BF)
#
###
    SofarModbusSensorEntityDescription(
        name="Solar Generation Today",
        key="solar_generation_today",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 0x684,
        newblock = True,
        unit = REGISTER_U32,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Solar Generation Total",
        key="solar_generation_total",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 0x686,
        unit = REGISTER_U32,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Load Consumption Today",
        key="load_consumption_today",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 0x688,
        unit = REGISTER_U32,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Load Consumption Total",
        key="load_consumption_total",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 0x68A,
        unit = REGISTER_U32,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Import Energy Today",
        key="import_energy_today",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 0x68C,
        unit = REGISTER_U32,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
        icon="mdi:home-import-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="Import Energy Total",
        key="import_energy_total",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 0x68E,
        unit = REGISTER_U32,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | PV,
        icon="mdi:home-import-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="Export Energy Today",
        key="export_energy_today",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 0x690,
        unit = REGISTER_U32,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID | PV,
        icon="mdi:home-export-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="Export Energy Total",
        key="export_energy_total",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 0x692,
        unit = REGISTER_U32,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | PV,
        icon="mdi:home-export-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Input Energy Today",
        key="battery_input_energy_today",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 0x694,
        unit = REGISTER_U32,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID,
        icon="mdi:battery-arrow-up",
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Input Energy Total",
        key="battery_input_energy_total",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 0x696,
        unit = REGISTER_U32,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID,
        icon="mdi:battery-arrow-up",
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Output Energy Today",
        key="battery_output_energy_today",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 0x698,
        unit = REGISTER_U32,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID,
        icon="mdi:battery-arrow-down",
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Output Energy Total",
        key="battery_Output_energy_total",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 0x69A,
        unit = REGISTER_U32,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID,
        icon="mdi:battery-arrow-down",
    ),

###
#
# Basic Parameter Configuration (0x1000-0x10FF)
#
###
    SofarModbusSensorEntityDescription(
        name = "EPS Control",
        key = "eps_control",
        register = 0x1029,
        newblock = True,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name = "Battery Active Control",
        key = "battery_active_control",
        register = 0x102B,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name = "Parallel Control",
        key = "parallel_control",
        register = 0x1035,
        allowedtypes = HYBRID | PV | X3 | PM,
    ),
    SofarModbusSensorEntityDescription(
        name = "Parallel Master-Salve",
        key = "parallel_masterslave",
        register = 0x1036,
        allowedtypes = HYBRID | PV | X3 | PM,
    ),
    SofarModbusSensorEntityDescription(
        name = "Parallel Address",
        key = "parallel_address",
        register = 0x1037,
        allowedtypes = HYBRID | PV | X3 | PM,
    ),
###
#
# Remote Control (0x1100-0x12FF)
#
###
    SofarModbusSensorEntityDescription(
        name = "Remote Control",
        key = "remote_control",
        register = 0x1104,
        newblock = True,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name = "Charger Use Mode",
        key = "charger_use_mode",
        register = 0x1110,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name = "Timing Charge On-Off",
        key = "timing_charge_onoff",
        register = 0x1112,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name = "Time of Use On-Off",
        key = "time_of_use_onoff",
        register = 0x1121,
        entity_registry_enabled_default=False,
        allowedtypes = HYBRID,
    ),
]
###
#
# Number
#
###
NUMBER_TYPES = [
    SofarModbusNumberEntityDescription(
        name = "Battery Minimum Capacity",
        key = "battery_minimum_capacity",
        register = 0x104D,
        fmt = "i",
        native_min_value = 1,
        native_max_value = 90,
        native_step = 1,
        native_unit_of_measurement = PERCENTAGE,
        allowedtypes = HYBRID,
        icon="mdi:battery-sync",
    ),
    SofarModbusNumberEntityDescription(
        name = "Battery Minimum Capacity OffGrid",
        key = "battery_minimum_capacity_offgrid",
        register = 0x104E,
        fmt = "i",
        native_min_value = 1,
        native_max_value = 90,
        native_step = 1,
        native_unit_of_measurement = PERCENTAGE,
        allowedtypes = HYBRID,
        icon="mdi:battery-sync",
    ),
    SofarModbusNumberEntityDescription(
        name = "Parallel Address",
        key = "parallel_address", 
        register = 0x1037,
        fmt = "i",
        native_min_value = 0,
        native_max_value = 10,
        native_step = 1,
        allowedtypes = HYBRID | PV | X3 | PM,
        entity_category = EntityCategory.CONFIG,
    ),
    SofarModbusNumberEntityDescription(
        name = "Time of Use Charge SOC",
        key = "time_of_use_charge_soc", 
        register = 0x1124,
        fmt = "i",
        native_min_value = 30,
        native_max_value = 100,
        native_step = 1,
        allowedtypes = HYBRID,
        entity_category = EntityCategory.CONFIG,
    ),
]
###
#
# Select
#
###
SELECT_TYPES = [
    SofarModbusSelectEntityDescription(
        name = "EPS Control",
        key = "eps_control",
        register = 0x1029,
        option_dict =  {
                0: "Turn Off",
                1: "Turn On, Prohibit Cold Start",
                2: "Turn On, Enable Cold Start",
            },
        allowedtypes = HYBRID | X3 | EPS,
    ),
    SofarModbusSelectEntityDescription(
        name = "Battery Active Control", # Not confirmed option
        key = "battery_active_control",
        register = 0x102B,
        option_dict =  {
                0: "Disabled",
                1: "Enabled",
            },
        allowedtypes = HYBRID,
    ),
    SofarModbusSelectEntityDescription(
        name = "Parallel Control",
        key = "parallel_control",
        register = 0x1035,
        option_dict =  {
                0: "Disabled",
                1: "Enabled",
            },
        allowedtypes = HYBRID | PV | X3 | PM,
    ),
    SofarModbusSelectEntityDescription(
        name = "Parallel Master-Salve",
        key = "parallel_masterslave",
        register = 0x1036,
        option_dict =  {
                0: "Slave",
                1: "Master",
            },
        allowedtypes = HYBRID | PV | X3 | PM,
    ),
    SofarModbusSelectEntityDescription(
        name = "Remote Control",
        key = "remote_control",
        register = 0x1104,
        option_dict =  {
                0: "Off",
                1: "On",
            },
        allowedtypes = HYBRID,
    ),
    SofarModbusSelectEntityDescription(
        name = "Charger Use Mode",
        key = "charger_use_mode",
        register = 0x1110,
        option_dict =  {
                0: "Self Use",
                1: "Time of Use",
                2: "Timing Mode",
                3: "Passive Mode",
                4: "Peak Cut Mode",
            },
        allowedtypes = HYBRID,
    ),
    SofarModbusSelectEntityDescription(
        name = "Timing Charge On-Off",
        key = "timing_charge_onoff",
        register = 0x1112,
        option_dict =  {
                0: "On",
                1: "Off",
            },
        allowedtypes = HYBRID,
    ),
    SofarModbusSelectEntityDescription(
        name = "Time of Use On-Off",
        key = "time_of_use_onoff",
        register = 0x1121,
        option_dict =  {
                0: "Disabled",
                1: "Enabled",
            },
        allowedtypes = HYBRID,
    ),
    # Timing Charge Start
    # Timing Charge End
    # Timing Discharge Start
    # Timing Discharge End
    # TOU Charge Start
    # TOU Charge End
]