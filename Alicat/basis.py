#!/usr/bin/env python
# coding: utf-8

# In[ ]:


import serial
import time
from math import log2
import minimalmodbus


# In[ ]:


class Basis(minimalmodbus.Instrument):
    """
    Extension of minimalmodbus https://pypi.org/project/MinimalModbus/
    which allows easy scripting and direct control of Alicat Basis units
    
    Large functionality changes occured with the update to firmware 
    version 2.4.0. Please contact Alicat if a command is incompatible
    with your firmware version.

    """
    
    def __init__(self, port: str = '/dev/ttyUSB0', baud: int = 38400, address: int = 1):
        
        minimalmodbus.Instrument.__init__(self, port, address)
        self.serial.baudrate = baud
        self.serial.timeout = 0.25
        self.port = port
    
    @property
    def baud(self):
        return self.serial.baudrate
    
    @baud.setter
    def baud(self, newbaud: int):
        bauds = {
            4800: 0,
            9600: 1,
            19200: 2,
            38400: 3,
            57600: 4,
            115200: 5
        }
        if bauds.get(newbaud, -1) != (-1):
            try:
                self.write_register(21,bauds[newbaud])
            except:
                pass
            finally:
                self.serial.baudrate = newbaud
        else:
            raise Exception('Invalid baudrate for this device. Please check available baudrates.')
    
    def _firmware_version(self):
        fw = self.read_register(25)
        return 'VERSION: ' + str(fw//256) + '.' + str(fw%256//16) + '.' + str(fw%256%16)
    
    def _serial_num(self):
        return self.read_string(26,5).replace(' ','')
    
    @property
    def fullscale(self):
        return self.read_float(47)/1000
    
    @property
    def units(self):
        u = {
            0: 'SCCM',
            1: 'SLPM'
        }
        return u[self.read_register(49)]
    
    @property
    def temperature(self):
        return float(self.read_register(2049))/100
    
    @property
    def mass_flow(self):
        return self.read_long(2050)/1000
    
    @property
    def valve_drive(self):
        return float(self.read_register(2052))/100
    
    @property
    def setpoint_source(self):
        return self.read_register(516)
    
    @setpoint_source.setter
    def setpoint_source(self, source: int):
        self.write_register(516, source)
    
    @property
    def setpoint(self):
        return float(self.read_long(2053))/1000
    
    @setpoint.setter
    def setpoint(self, setpoint: float):
        if not self.setpoint_source:
            self.setpoint_source = 2
        self.write_long(2053,int(setpoint * 1000))
        
    @property
    def gas(self):
        g = self.read_register(2048)
        gases = {
            0: 'Air',
            1: 'Ar',
            2: 'CO2',
            3: 'N2',
            4: 'O2',
            5: 'N2O',
            6: 'H2',
            7: 'He'
        }
        return gases[g]
    
    @gas.setter
    def gas(self,newgas: str):
        gases = {
            'Air': 0,
            'Ar': 1,
            'CO2': 2,
            'N2': 3,
            'O2': 4,
            'N2O': 5,
            'H2': 6,
            'He': 7
        }
        if gases.get(newgas, -1) != (-1):
            self.write_register(2048, gases[newgas])
        else:
            raise Exception('Invalid gas selection. Please check available gases.')
    
    @property
    def p_gain(self):
        return self.read_register(519)
    
    @property
    def i_gain(self):
        return self.read_register(520)
    
    @p_gain.setter
    def p_gain(self, gain):
        self.write_register(519, gain)
        
    @i_gain.setter
    def i_gain(self, gain):
        self.write_register(520, gain)
        
    @property
    def sp_watchdog(self):
        return self.read_register(514)
    
    @sp_watchdog.setter
    def sp_watchdog(self, time):
        self.write_register(514, time)
        
    @property
    def stp_temp(self):
        return float(self.read_register(52))/100
    
    @stp_temp.setter
    def stp_temp(self, temp):
        self.write_register(52, int(temp * 100))
    
    @property
    def averaging_time(self):
        return 2.5 * 2 ** self.read_register(40)
    
    @averaging_time.setter
    def averaging_time(self, time: float):
        time /= 2.5
        time  = int(log2(time))
        if time <= 9:
            self.write_register(40, time)
        else: raise Exception('time averaging too long, must be less than')
    
    @property
    def modbus_ID(self):
        return self.read_register(45)
    
    @property
    def ascii_ID(self):
        return self.read_register(46)
    
    @modbus_ID.setter
    def modbus_ID(self, ID: int):
        if ID < 1 or ID > 247:
            raise ValueError('Modbus ID outside of valid range')
        self.write_register(45, ID)
        self.address = ID
        
    @ascii_ID.setter
    def ascii_ID(self, ID: str):
        ID = ID.upper().strip()
        if ID != ID[0]:
            raise Exception('ASCII ID must be a single character A-Z')
        if ID >= 'Z' or ID <= 'A':
            raise Exception('ID value must be alphabetical')
        self.write_register(46, ord(ID))
        
    @property
    def exhaust(self):
        return self.read_register(512)
    
    @exhaust.setter
    def exhaust(self, val: bool):
        self.write_register(512, 1) if val else self.write_register(512, 0)
        
    @property
    def exhaust_valve(self):
        return self.read_register(513)
    
    @exhaust_valve.setter
    def exhaust_valve(self, drive):
        self.write_register(513, int(drive * 100))
    
    def tare_flow(self):
        self.write_register(39, 43605)
        time.sleep(1)
        
    @property
    def dataframe(self):
        return [self.modbus_ID, self.temperature,         self.mass_flow, self.gas]

