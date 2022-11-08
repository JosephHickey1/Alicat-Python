#!/usr/bin/env python
# coding: utf-8

# In[ ]:


import serial
import time
import minimalmodbus


# In[ ]:


class CODA(minimalmodbus.Instrument):
    """
    Extension of minimalmodbus https://pypi.org/project/MinimalModbus/
    which allows for scripting and direct control of Alicat CODA units
    """
    
    def __init__(self, port: str = '/dev/ttyUSB0', baud: int = 19200, address: int = 1):
        
        minimalmodbus.Instrument.__init__(self, port, address)
        self.serial.baudrate = baud
        self.serial.timeout = 0.25
        self.port = port
        
        
    @property
    def baud(self):
        return self.serial.baudrate
    
    @property
    def density(self):
        return self.read_float(1202)
    
    @property
    def temperature(self):
        return self.read_float(1204)
    
    @property
    def volume_flow(self):
        return self.read_float(1206)
    
    @property
    def mass_flow(self):
        return self.read_float(1208)
    
    @property
    def total_mass(self):
        return self.read_float(1210)
    
    
    @property
    def setpoint(self):
        return self.read_float(1212)
    
    @setpoint.setter
    def setpoint(self, setpoint: float):
        if self.read_status() == 'taring':
            raise Warning('Device is currently taring, do not start flow')
        self.write_float(1011, float(setpoint))
        
        
    @property
    def total_time(self):
        return self.read_float(1214)
    
    
    @property
    def percent_setpoint(self):
        return self.read_float(2048)
    
    @percent_setpoint.setter
    def percent_setpoint(self, setpoint: float):
        if self.read_status() == 'taring':
            raise Warning('Device is currently taring, do not start flow')
        self.write_float(1009, float(setpoint))
    
    
    @property
    def modbus_ID(self):
        return self.read_register(2052)
    
    
    @property
    def vol_overrange(self):
        return self.read_register(2054)
    
    @property
    def mass_overrange(self):
        return self.read_register(2055)
    
    @property
    def temperature_overrange(self):
        return self.read_register(2056)
    
    @property
    def total_overrange(self):
        return self.read_register(2057)
    
    
    def status(self):
        return self.read_long(1200)
    
    def read_status(self):
        byte = self.status()
        if byte == 0:
            return 'taring'
        elif byte == 1:
            return 'density underrange'
        elif byte == 2:
            return 'density overrange'
        else:
            return 'no flags'
    
    
    @property
    def sefa_gain(self):
        return self.read_float(1109)
    
    @sefa_gain.setter
    def sefa_gain(self, gain: float):
        self.write_float(1109, gain)
    
    
    @property
    def p_gain(self):
        return self.read_float(1119)
    
    @p_gain.setter
    def p_gain(self, gain: float):
        self.write_float(1119, gain)
    
    
    @property
    def i_gain(self):
        return self.read_float(1121)
    
    @i_gain.setter
    def i_gain(self, gain: float):
        self.write_float(1121, gain)
    
    
    @property
    def d_gain(self):
        return self.read_float(1123)
    
    @d_gain.setter
    def d_gain(self, gain: float):
        self.write_float(1123, gain)
    
    
    @property
    def valve_offset(self):
        return self.read_float(1125)
    
    @valve_offset.setter
    def valve_offset(self, offset: float):
        self.write_float(1125, offset)
    
    
    @property
    def fullscale(self):
        return self.read_float(1107)
    
    
    @property
    def dataframe(self):
        return [self.modbus_ID, self.density, self.temperature,                 self.volume_flow, self.mass_flow, self.setpoint,                 self.total_mass, self.total_time]
    
    
    def command_result(self):
        c, arg = self.read_registers(999, 2)
        if arg:
            if arg == 32769:
                raise Exception(f'{c} is not a valid command ID')
            elif arg == 32770:
                raise Exception('This setting is not valid')
            else:
                raise Exception('The requested feature is not supported on this device')
        return
    
    def command(self, ID: int, arg: int):
        self.write_registers(999,[ID, arg])
        self.command_result()
    
    
    def tare_flow(self):
        self.command(4,1)
            
    def abort_tare(self):
        self.command(4,0)
        
        
    def reset_totalizer(self):
        self.command(5,0)
        
    def pause_totalizer(self):
        self.command(15,0)
        
    def resume_totalizer(self):
        self.command(15,1)
        
        
    def control_mass(self):
        self.command(11,0)
        
    def control_volume(self):
        self.command(11,1)
    
    
    def powerup_setpoint(self, setpoint: float):
        self.setpoint = setpoint
    
    
    def save_pid_gains(self):
        self.command(17,1)
        
        
    def digital_setpoint(self):
        self.command(18,0)
    
    def analog_setpoint(self):
        self.command(18,1)
    
    
    def valve_hold(self, state: str):
        states = {
            'cancel': 0,
            'close': 1,
            'open': 2
        }
        self.command(16, states[state])
        
        
    def power_lost(self):
        self.serial.close()
        time.sleep(0.5)
        self.serial.open()
        
    
    def close(self):
        self.serial.close()
    
    
    

