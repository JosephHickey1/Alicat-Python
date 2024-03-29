#!/usr/bin/env python
# coding: utf-8

# These classes form the backbone of Alicat operations through serial commmands

# In[1]:


import serial
import pickle
import time
import os


# In[3]:


class Serial_Connection(object):
    """The serial connection object from which other classes inherit port and baud settings as
    well as reading and writing capabilities. Preprocessing for GP firmware outputs is performed
    using the remove_characters function"""
    
    # A dictionary storing open serial ports for comparison 
    # with new connections being opened
    open_ports = {}

    def __init__(self, port='/dev/ttyUSB0', baud=19200):

        self.port, self.baud = port, baud

        # Checks for the existence of an identical port to avoid multiple instances
        # creates a new one if none exists
        if port in Serial_Connection.open_ports:
            self.connection = Serial_Connection.open_ports[port]
        else:
            self.connection = serial.Serial(port, baud, timeout=2.0)
            Serial_Connection.open_ports[port] = self.connection

        self.open = True


    def _test_open(self):

        if not self.open:
            raise IOError(f"The connection to Alicats on port {self.port} not open")


    def _flush(self):
        """Deletes all characters in the read/write buffer to avoid double messages or rewrites"""
        self._test_open()

        self.connection.flush()
        self.connection.flushInput()
        self.connection.flushOutput()


    def _close(self):
        """Checks if the instance exists, clears the buffer, closes the connection, and removes
        itself from the dictionary of active ports"""
        if not self.open:
            return

        self._flush()

        self.connection.close()
        Serial_Connection.open_ports.pop(self.port, None)

        self.open = False


    def _read(self):
        """Fast read method using byte arrays with a carriage return delimiter between lines.
        ~30x faster than a readline operation by reading individual characters and appending 
        them to the byte array. The byte array is then decoded into a string and returned"""
        self._test_open()

        line = bytearray()
        while True:
            c = self.connection.read(1)
            if c:
                line += c
                if line[-1] == ord('\r'):
                    break
            else:
                break

        return line.decode('ascii').strip().replace('\x08','')


    def _write(self, ID, command, verbose=False):
        """Writes the input command for a device with the stated ID by encoding to ascii
        and sending through the serial connection write command. Reads out the return parsing 
        multiple lines until the buffer is clear."""
        # Generate command string with carriage return '\r'
        command = str(ID) + str(command) + '\r'
        command = command.encode('ascii')
        self.connection.write(command)
        # If True, returns each line of response in a list, else clear responses
        if verbose:
            response = []
            response.append(self._read())
            while True:
                if response[-1] != '':
                    response.append(self._read())
                else:
                    return response[:-1]

        else:
            self._flush()


# In[3]:


class MassFlowMeter(Serial_Connection):
    """Base laminar dP mass flow object which contains all functions specific to mass flow devices.
    Initial creation of the object is slow as many characteristics are retrieved and parsed.
    Future versions may allow the passing of a config file to initialize settings."""

    def __init__(self, ID :str ='A', port : str ='/dev/ttyUSB0', baud : int =19200, config = None):
        # Initialize a serial connection for commuication with the device
        super().__init__(port, baud)
        self.ID, self.port, self.baud = ID, port, baud
        self.variables = {}
        if config:
            curdir = os.getcwd()
            os.chdir(os.path.abspath('deviceconfigs'))
            with open(config, 'rb') as f:
                self.variables = pickle.loads(f.read())
            os.chdir(curdir)

            self.firmware_version, self.firmware_minor = self.variables['firmware_version'], self.variables['firmware_minor']

        else:
            # Gather device information and specific formatting for data
            self._fetch_gas_list()
            self._fetch_device_data()
            self._data_format()
            self.variables['current_gas'] = self._write(self.ID,'',True)[-1].split()[-1]
            self.variables['gas_changes'] = 0
            self.variables['setpoint_changes'] = 0
            self._eeprom_saving(read=True)

            # Stores full scale range of device measurements
            self.variables['mfullscale'] = self._get_fullscale('mass')
            self.variables['pfullscale'] = self._get_fullscale('pressure')
            self.variables['vfullscale'] = self._get_fullscale('volumetric')
            self.variables['scales'] = {'mass': self.variables['mfullscale'],
                                        'volumetric': self.variables['vfullscale'],
                                        'volume': self.variables['vfullscale'],
                                        'pressure': self.variables['pfullscale']}


    def __str__(self):
        return self.variables['serialnum']


    def _eeprom_saving(self, read: bool = False, setting = 'setpoint', state: bool = False):
        # Enables or diables EEPROM saving for setpoint
        r18 = int(self._write(self.ID,'$$R18',True)[0].split()[3])
        if read:
            self.variables['ram_only_setpoint'] = 0 if (r18 & 32768) else 1
            self.variables['ram_only_gas'] = 1 if (r18 & 2048) else 0
            return

        if setting == 'setpoint':
            if not state and (r18 & 32768):
                r18 -= 32768
            elif state and not (r18 & 32768):
                r18 += 32768
        elif setting == 'gas':
            if state and (r18 & 2048):
                r18 -= 2048
            elif not state and not (r18 & 2048):
                r18 +=2048

        self._write(self.ID,f'$$W=18{r18}')
        self._eeprom_saving(read=True)


    def _fetch_gas_list(self):
        # Empty dictionaries to store gas and index information
        self.variables['gas_list'] = {}
        self.variables['gas_ref'] = {}
        self.variables['reverse_gas_list'] = {}

        # Query gas table for index and short name
        gases = [i.split() for i in self._write(self.ID, '??G*',True)]

        # Save gas data in dictionaries
        for i in range(len(gases)):
            self.variables['gas_list'][gases[i][2]] = int(gases[i][1][1:])
            self.variables['gas_ref'][int(gases[i][1][1:])] = int(gases[i][1][1:])
            self.variables['reverse_gas_list'][int(gases[i][1][1:])] = gases[i][2]
            self.variables['gas_ref'].update(self.variables['gas_list'])
        del gases


    def _fetch_device_data(self):
        # Query manufacturer data saving only the firmware version
        manufacturer_data = [i.split() for i in self._write(self.ID, '??M*',True)]
        self.variables['serialnum'] = manufacturer_data[5][-1]
        self.variables['firmware_version'] = manufacturer_data[-1][-1]
        self.firmware_version = self.variables['firmware_version']

        # Early firmware version would present the version with a 
        # capitalized 'V' between major and minor version
        if self.variables['firmware_version'][:2] != 'GP':
            self.variables['firmware_version'], self.variables['firmware_minor'] = self.variables['firmware_version'].replace('V','v').split('v',1)
            self.variables['firmware_version'] = int(self.variables['firmware_version'])
        else:
            # Safe to assume all GP units still functioning were of the 07 release
            self.variables['firmware_version'], self.variables['firmware_minor'] = 'GP', '07'

        self.firmware_version, self.firmware_minor = self.variables['firmware_version'], self.variables['firmware_minor']

    def _data_format(self):
        """Uses serial command for querying the format of general poll dataframe and parses the
        output based on firmware version to get a list of parameters being sent over serial and
        a readable list of parameter name and units"""
        self.variables['data'] = []
        # Reads in format data for parsing
        outputs = [i.split() for i in self._write(self.ID,'??D*',True)]
        for i in range(len(outputs)):
            outputs[i][1] = outputs[i][1][1:]
        # Checks firmware version as the format of the format output changed with 6v firmware
        if isinstance(self.firmware_version, str) or self.firmware_version < 6:
            # For 6v and older format
            self.variables['ranges'] = {}
            for i in range(2, len(outputs)):
                c = outputs[i]
                if c[-1] == 'na' or c[-1] == '_':
                    del c[-1]
                # Appends parameter ID, Parameter Name, and Parameter Units for each parameter
                self.variables['data'].append([int(c[1]), c[2], c[-1]])
                self.variables['ranges'][c[2].lower()] = c[-2]

        else:
            # for 7v and newer format
            output2 = []
            for i in range(len(outputs)):
                c = outputs[i]
                # Convert all to integers that can be and pass the error for non-numerics
                for i in range(len(c)):
                    try:
                        c[i] = int(c[i])
                    except ValueError:
                        pass
                # Create screen to catch and contatenate split parameter names
                seq = 0
                for i in range(len(c)):
                    if isinstance(c[i],str) and c[i] != 's' and c[i] != 'string' and c[i] != 'decimal':
                        seq += 1
                        if seq > 1:
                            c[i-seq+1] += ' ' + c[i]
                    else:
                        seq = 0
                # Add the reformated and concatenated list to the outputs
                output2.append(c)
            # Take only the Parameter ID, Parameter Name, and Parameter Units for each parameter
            for i in range(2, len(output2)):
                self.variables['data'].append([output2[i][2], output2[i][3], output2[i][-1]])
        # Delete temporary arrays
            del output2
        del outputs
        # Generate keys for the `get` command
        self.variables['keys'] = [self.variables['data'][i][1] for i in range(len(self.variables['data']))]


    def _get_fullscale(self, statistic = 'mass'):
        # Determines fullscale of each statistic in current engineering units
        # May be moved due to shared properties with MassFlowMeter
        exch = {'mass' : 5, 'volumetric': 4, 'pressure': 2}
        if isinstance(self.firmware_version, str) or self.firmware_version < 6:
            return float(self.variables['ranges'][statistic])
        else:
            response = self._write(self.ID, f'FPF {exch[statistic]}', True)
            return float(response[0].split()[1])


    def _print_dataframe(self,iterations=1):
        # Prints a number of lines of data from the device. 
        # Data is in the same order as self.data
        dataframe = []
        for i in range(iterations):
            dataframe.append(self._write(self.ID,'',True))
        return dataframe


    def get(self):
        # Returns a dictionary of current values bound to their parameter name
        data = self._write(self.ID,'',True)[0].split()[1:]
        values = {k: v for k,v in zip(self.variables['keys'], data)}
        return values


    def set_gas(self, gas):
        # Changes gas to the new gas selected taking either the short name or index
        if int(self.variables['gas_ref'][gas]) != int(self.variables['gas_ref'][self.variables['current_gas']]):
            var = self.variables['gas_ref'][gas]
            self._write(self.ID, f'$$G{var}')
            self.variables['current_gas'] = self.variables['reverse_gas_list'][int(self.variables['gas_ref'][gas])]
            
            self.variables['gas_changes'] += 1
            if self.variables['gas_changes'] > 10000 and not self.variables['ram_only_gas']:
                self._eeprom_saving(setting='gas',state=False)


    def create_mix(self, gases: list, percentages: list):
        pass
#    

    def delete_mix(self, mixnum):
        pass
#    

    def lock(self):
        # Locks the front display from making settings changes
        self._write(self.ID,'$$L')


    def unlock(self):
        # Unlocks front display
        self._write(self.ID,'$$U')


    def tare_press(self):
        # Tares absolute pressure 
        if self.firmware_version == 'GP' or self.firmware_version < 6:
            self._write(self.ID,'$$P')
        else:
            self._write(self.ID,'$$PC')


    def tare_flow(self):
        # Tares mass and volumetric flow
        self._write(self.ID,'$$V')


    def totalizer_reset(self):
        # Resets/Tares totalizer, resets totalizer batch for controllers
        self._write(self.ID,'$$T')


    def change_id(self, newid: str):
        # Changes ASCII alphabetical unit ID
        if newid.upper() != self.ID:
            val = 256 * ord(newid.upper())
            reg = int(self._write(self.ID,'$$R17',True)[0].split()[-1])
            reg += val - (256 * ord(self.ID.upper()))
            self._write(self.ID,f'$$W17={reg}')
            self.ID = newid.upper()


    def change_baud(self, newbaud: int):
        # Changes baud rate and reinstantiates the serial connection with the new baud rate
        if newbaud != self.baud:
            # GP firmware devices used a different set of value: baud pairs
            # Baud rate updates also required a hard restart of the device itself
            if isinstance(self.firmware_version, str):
                bauds = {2400 : 0, 9600: 1, 19200: 2, 38400: 3}
                idval = 256 * ord(self.ID)
                val = idval + bauds[newbaud]
                print(val)
                self._write(self.ID,f'$$W17={val}')
            # Non-GP units could update baud rate without a restart and had a larger range of baud rates
            else:
                bauds = {2400: 0, 9600: 1, 19200: 2, 38400: 3, 57600: 4, 115200: 5}
                if newbaud == 57600 or 115200:
                    r87 = int(self._write(self.ID,'$$R87', True)[0].split()[-1]) 
                    self._write(self.ID,f'$$W87={r87 + 2 - (r87 & 2)}')
                idval = 256 * ord(self.ID)
                val = 240 + idval + bauds[newbaud]
                self._write(self.ID,f'$$W17={val}')
            # Replace baud rate property, close old connection, and open a new one
            self.baud = newbaud
            self._close()
            super().__init__(self.port, self.baud)


    def change_stp(self, standardtemp, standardpress):
        # Change Standard Temperature and Pressure in units of Celsius and PSIA
        # Used for flow units starting with 'S' (SLPM, SCCM, Sin3/m, etc.)
        if self.firmware_version == 'GP':
            raise Exception('STP modification is not available in this firmware version')
        else:
            temp = (standardtemp + 273.15) * 100000
            press = standardpress * 100000
            self._write(self.ID, f'$$W137={temp}')
            self._write(self.ID, f'$$W138={press}')


    def change_ntp(self, normaltemp, normalpress):
        # Change Normal Temperature and Pressure in units of Celsius and PSIA
        # Used for flow units starting with 'N' (NLPM, NCCM, Nin3/m, etc.)
        if self.firmware_version == 'GP':
            raise Exception('NTP modification is not available in this firmware version')
        else:
            temp = (normaltemp + 273.15) * 100000
            press = normalpress * 100000
            self._write(self.ID, f'$$W139={temp}')
            self._write(self.ID, f'$$W140={press}')


    def set_alarm(self, expression: str = ''):
        # Sets a new alarm using the set and clear expressions in RPN
        # Configuration info can be found at: 
        # https://www.alicat.com/using-your-alicat/alarm-function-ale-command-tutorial/
        self._write(self.ID,f' ALE {expression}')


    def factory_restore(self):
        # Restores device to factory settings
        if self.firmware_version == 'GP':
            raise Exception('Restoration of factory defaults is not available on this device.')
        elif self.firmware_version >= 7:
            self._write(self.ID,' FACTORY RESTORE ALL')
            time.sleep(10)
            self._flush()
        else:
            self.write(self.ID,'$$W5683=128')
            self.write(self.ID,'Z')
            time.sleep(10)
            self._flush()


# In[4]:


class MassFlowController(MassFlowMeter):
    """Controller class which extends the functionality of the MassFlowMeter class with options for control
    loop tuning, setpoint ramping, and control variable switching. Initialization is still slow due to the
    parent class initialization."""

    def __init__(self, ID :str ='A', port : str ='/dev/ttyUSB0', baud : int =19200, config = None):
        # Configure the device for scripted control and
        # gathers further data about the device
        super().__init__(ID, port, baud, config)
        self.change_control_var(read=True)


    def set_setpoint(self, setpoint: float = 0):
        # Takes a setpoint in floating point value and commands device with it
        # GP devices only accepted integer counts of fullscale so a conversion is done
        if self.firmware_version == 'GP' or self.firmware_version < 6:
            setpoint = str(int(64000 * setpoint // (self.variables['fullscale'])))
            self._write(self.ID, setpoint)
        else:
            self._write(self.ID, f'S{setpoint}')
        self.variables['setpoint'] = setpoint
        self.variables['setpoint_changes'] += 1
        if self.variables['setpoint_changes'] > 100000 and not self.variables['ram_only_setpoint']:
            self.eeprom_saving(setting='setpoint',state=False)


    def set_batch(self, batchsize):
        # Sets the size of a single batch and resets the totalizer
        # Subsequent batches can be reset using the <Object>.totalizer_reset() method
        if self.firmware_version == 'GP':
            raise Exception('This function is not available for units with GP firmware.')
        self.totalizer_reset()
        self._write(self.ID,f'$$W93={batchsize}')


    def valve_hold(self):
        # Holds the valve at the current position
        self._write(self.ID,'$$H')


    def valve_hold_closed(self):
        # Holds the valves closed
        self._write(self.ID,'$$HC')


    def cancel_hold(self):
        # Cancels hold and resumes active control
        self._write(self.ID,'$$C')


    def pid(self, P=0, I=0, D=0, read=True):
        # Sets or returns PID gains
        if read:
            pid = {}
            pid['P'] = int(self._write(self.ID,'$$R21',True)[0].split()[3])
            pid['D'] = int(self._write(self.ID,'$$R22',True)[0].split()[3])
            pid['I'] = int(self._write(self.ID,'$$R23',True)[0].split()[3])
            pid['Loop'] = self.pid_loop(read=True)
            return pid

        self._write(self.ID,f'$$W21={P}')
        time.sleep(1)
        self._write(self.ID,f'$$W22={D}')
        time.sleep(1)
        self._write(self.ID,f'$$W23={I}')


    def pid_loop(self, loop = 0, read = True, verbose = False):
        # Sets or reads the control loop type of the device
        loops = {0: 'PDF', 1: 'PD2I'}

        # Determines where loop type information is stored
        if read:
            addr = 23 if self.firmware_version == 'GP' else 85
            val = int(self._write(self.ID, f'$$R{addr}', True)[0].split()[3])
            if addr == 23 and (val & 1):
                loop = 1 if (val & 1) else 0
            else:
                loop = 0 if (val == 0 or val == 1) else 1
            return loops[loop]

        # GP units used the least significant bit to determine loop type 
        if self.firmware_version == 'GP':
            val = int(self._write(self.ID, '$$R23', True)[0].split()[3])
            self.variables['current_loop'] = 1 if val & 1 else 0
            if read:
                print(f'The current control loop is set to {loops[loop]}')

            if loop == 'PDF' and self.variables['current_loop'] != 0:
                val -= 1
                self._write(self.ID,f'$$W23={val}')
                self.variables['current_loop'] = 0
            elif (loop == 'PDDI' or loop == 'PD2I') and self.variables['current_loop'] != 1:
                val += 1
                self._write(self.ID,f'$$W23={val}')
                self.variables['current_loop'] = 1
            else:
                pass
        # Modern units differentiate between single and dual valve devices
        else:
            val = int(self._write(self.ID,'$$R85',True)[0].split()[3])
            if loop == ('PDF' or 0):
                val = 0
            elif loop == ('PDDI' or 'PD2I' or 1):
                val = 32770 if val > 2 else 2
            else:
                pass
            self._write(self.ID,f'$$W85={val}')

        # Optional print out of the change
        if verbose:
            print(f'The control loop has been set to {loops[loop]}')


    def change_control_var(self, variable = 'mass', read=False):
        # Changes the parameter for the setpoint and for feeding into the control loop
        # Changing the parameter may necessitate new PID tuning terms 
        reg = int(self._write(self.ID,'$$R20', True)[0].split()[3].lstrip())

        # Loop parameter is determined by bits flipped in register 20
        loop = {'mass': 1024, 'volume': 768, 'volumetric': 768, 'pressure': 256}
        if reg & 1024:
            var = 1024
        elif (reg  & 512) and (reg & 256):
            var = 768
        else:
            var = 256

        if read:
            self.variables['control_variable'] = loop[variable]
            self.variables['fullscale'] = self.variables['scales'][variable]
            return

        if var != loop[variable]:
            reg = reg - var + loop[variable]
            self._write(self.ID,f'$$W20={reg}')

        # Changes loop variable property and which fullscale is used
        self.variables['control_variable'] = loop[variable]
        self.variables['fullscale'] = self.variables['scales'][variable]


    def setpoint_ramp(self, step_size=0, timedelta=0):
        # Creates a limit to the setpoint increase as a function of time allowing
        # slower adjustments outside of the PID domain
        if isinstance(self.firmware_version,str) or self.firmware_version < 8:
            raise Exception('This function is not available for units with firmware earlier than 8v.')
        step = step_size * 64000 // self.variables['mfullscale']
        self._write(self.ID,f'$$W160={step}')
        time.sleep(1)
        self._write(self.ID,f'$$W161={timedelta}')


    def set_autotare(self, delay):
        # Sets the power-up and auto tare time delay. A value of zero disables them.
        r18 = int(self._write(self.ID,'$$R18',True)[0].split()[3])
        old = r18 & 255
        new = r18 - old + delay
        self._write(self.ID,f'$$W18={new}')
        r19 = int(self._write(self.ID,'$$R19',True)[0].split()[3])
        r20 = int(self._write(self.ID,'$$R20',True)[0].split()[3])
        old = r19 & 255

        # Auto Tare is enabled/disabled through register 20 but configured through 19
        if delay > 0:
            self._write(self.ID,f'$$W20={r20 + 8192 - (r20 & 8192)}')
            time.sleep(1)
            new = r19 - old + delay
            self._write(self.ID,f'$$W19={new}')
        else:
            self._write(self.ID,f'$$W20{r20 - (r20 & 8192)}')


    def powerup_setpoint(self, setpoint):
        # Enables a power-up setpoint for the device

        r18 = int(self._write(self.ID,'$$R18',True)[0].split()[3])

        if self.variables['ram_only_setpoint']:
            # Temporarily enable EEPROM saving
            r18 += 32768
            self._write(self.ID,f'$$W18={r18}')
            time.sleep(1)

        # Write new setpoint to save in EEPROM
        self.set_setpoint(setpoint)
        time.sleep(1)

        # Disable saving with new setpoint stored
        r18 -= 32768
        self._write(self.ID,f'$$W18={r18}')


    def setpoint_limits(self, minimum, maximum):
        # Limit the acceptable setpoints the controller will use
        if (isinstance(self.firmware_version,str) or self.firmware_version < 8):
            raise Exception('This function is not available for units with firmware earlier than 8v.')

        # Convert and write minimum and maximum values as device counts
        if minimum:
            self._write(self.ID,f'$$W169={minimum * 64000 / self.fullscale}')
            time.sleep(1)
        if maximum:
            self._write(self.ID,f'$$W170={maximum * 64000 / self.fullscale}')


    def flow_limit(self, limit):
        # Sets a limit to the flow rate while in pressure control mode
        # If controlling on pressure and totalizing flow, this should be set <= self.mfullscale
        if (isinstance(self.firmware_version,str) or self.firmware_version < 8):
            raise Exception('This function is not available for units with firmware earlier than 8v.')
        mfullscale = self.variables['mfullscale']
        self._write(self.ID,f'$$W165={limit * 64000 / mfullscale}')


    def control_deadband(self, deadband):
        # Set a custom deadband in device units which the control algortihm considers
        # the reading and setpoint to be equivalent. Used for increased system stability.
        self._write(self.ID,f'$$W58={deadband * 64000 / self.fullscale}')


    def overpressure_limit(self, limit):
        # Set a limit in device units for pressure which upon reaching, the valve will close
        # Send a new setpoint command to resume active control
        pfullscale = self.variables['pfullscale']
        self._write(Self.ID,f'$$W73{limit * 64000 / pfullscale}')


# In[5]:


class PressureMeter(Serial_Connection):
    """Base pressure object which contains all functions specific to pressure devices.
    Initial creation of the object is slow as many characteristics are retrieved and parsed.
    Future versions may allow the passing of a config file to initialize settings."""

    def __init__(self, ID :str ='A', port : str ='/dev/ttyUSB0', baud : int =19200, config = None):
        # Initialize a serial connection for commuication with the device
        super().__init__(port, baud)
        self.ID, self.port, self.baud = ID, port, baud
        self.variables = {}

        if config:
            curdir = os.getcwd()
            os.chdir(os.path.abspath('deviceconfigs'))
            with open(config, 'rb') as f:
                self.variables = pickle.loads(f.read())
            os.chdir(curdir)

            self.firmware_version, self.firmware_minor = self.variables['firmware_version'], self.variables['firmware_minor']

        else:
            # Gather device information and specific formatting for data
            self._fetch_device_data()
            self._data_format()

            # Stores full scale range of the pressure statistic this device works with
            fullscale = self._get_fullscale('Dif Press')
            if fullscale == 0:
                fullscale = self._get_fullscale('Ga Press')
            if fullscale == 0:
                fullscale = self._get_fullscale('Abs Press')
            self.variables['fullscale'] = fullscale


    def __str__(self):
        return self.variables['serialnum']


    def _fetch_device_data(self):
        # Query manufacturer data saving only the firmware version
        manufacturer_data = [i.split() for i in self._write(self.ID, '??M*',True)]
        self.variables['serialnum'] = manufacturer_data[5][-1]
        firmware_version = manufacturer_data[-1][-1]

        # Early firmware version would present the version with a capitalized 'V' between major and minor version
        self.variables['firmware_version'], self.variables['firmware_minor'] = firmware_version.replace('V','v').split('v',1)
        self.variables['firmware_version'] = int(self.variables['firmware_version'])
        self.firmware_version = self.variables['firmware_version']

    def _data_format(self):
        """Uses serial command for querying the format of general poll dataframe and parses the
        output based on firmware version to get a list of parameters being sent over serial and
        a readable list of parameter name and units"""
        self.variables['data'] = []
        # Reads in format data for parsing
        outputs = [i.split() for i in self._write(self.ID,'??D*',True)]
        for i in range(len(outputs)):
            outputs[i][1] = outputs[i][1][1:]
        # Checks firmware version as the format of the format output changed with 6v firmware
        if self.firmware_version < 6:
            # For 6v and older format
            self.ranges = {}
            for i in range(2, len(outputs)):
                c = outputs[i]
                if c[-1] == 'na' or c[-1] == '_':
                    del c[-1]
                # Appends parameter ID, Parameter Name, and Parameter Units for each parameter
                self.variables['data'].append([int(c[1]), c[2], c[-1]])
                self.variables['ranges'][c[2].lower()] = c[-2]

        else:
            # for 6v and newer format
            output2 = []
            for i in range(len(outputs)):
                c = outputs[i]
                # Convert all to integers that can be and pass the error for non-numerics
                for i in range(len(c)):
                    try:
                        c[i] = int(c[i])
                    except ValueError:
                        pass
                # Create screen to catch and contatenate split parameter names
                seq = 0
                for i in range(len(c)):
                    if isinstance(c[i],str) and c[i] != 's' and c[i] != 'string' and c[i] != 'decimal':
                        seq += 1
                        if seq > 1:
                            c[i-seq+1] += ' ' + c[i]
                    else:
                        seq = 0
                # Add the reformated and concatenated list to the outputs
                output2.append(c)
            # Take only the Parameter ID, Parameter Name, and Parameter Units for each parameter
            for i in range(2, len(output2)):
                self.variables['data'].append([output2[i][2], output2[i][3], output2[i][-1]])
        # Delete temporary arrays
            del output2
        del outputs
        # Generate keys for the `get` command
        self.variables['keys'] = [self.variables['data'][i][1] for i in range(len(self.variables['data']))]


    def _get_fullscale(self, statistic):
        # Determines fullscale of each statistic in current engineering units
        if self.firmware_version < 6:
            return float(self.variables['ranges'][statistic])
        else:
            params = {'Abs Press': 2, 'Ga Press': 6, 'Dif Press': 7}
            response = self._write(self.ID, f'FPF {params[statistic]}', True)
            return float(response[0].split()[1])


    def _print_dataframe(self,iterations=1):
        # Prints a number of lines of data from the device. Data is in the same order as self.data
        dataframe = []
        for i in range(iterations):
            dataframe.append(self._write(self.ID,'',True))
        return dataframe


    def get(self):
        # Returns a dictionary of current values bound to their parameter name
        data = self._write(self.ID,'',True)[0].split()[1:]
        values = {k: v for k,v in zip(self.variables['keys'], data)}
        return values


    def lock(self):
        # Locks the front display from making settings changes
        self._write(self.ID,'$$L')


    def unlock(self):
        # Unlocks front display
        self._write(self.ID,'$$U')


    def tare_press(self):
        # Tares absolute pressure 
        self._write(self.ID,'$$P')


    def change_id(self, newid: str):
        # Changes ASCII alphabetical unit ID
        if newid.upper() != self.ID:
            val = 256 * ord(newid.upper())
            reg = int(self._write(self.ID,'$$R17',True)[0].split()[-1])
            reg += val - (256 * ord(self.ID.upper()))
            self._write(self.ID,f'$$W17={reg}')
            self.ID = newid.upper()


    def change_baud(self, newbaud: int):
        # Changes baud rate and reinstantiates the serial connection with the new baud rate
        if newbaud != self.baud:
            bauds = {2400: 0, 9600: 1, 19200: 2, 38400: 3, 57600: 4, 115200: 5}
            if newbaud == 57600 or 115200:
                r87 = int(self._write(self.ID,'$$R87', True)[0].split()[-1]) 
                # Change to read_register call when implemented
                self._write(self.ID,f'$$W87={r87 + 2 - (r87 & 2)}')
                time.sleep(1)
            idval = 256 * ord(self.ID)
            self._write(self.ID,f'W17={idval + bauds[newbaud] + 240}')
            # Replace baud rate property, close old connection, and open a new one
            self.baud = newbaud
            self._close()
            super().__init__(self.port, self.baud)


    def set_alarm(self, expression: str = ''):
        # Sets a new alarm using the set and clear expressions in RPN
        # Configuration info can be found at: https://www.alicat.com/using-your-alicat/alarm-function-ale-command-tutorial/
        self._write(self.ID,f' ALE {expression}')


    def factory_restore(self):
        # Restores device to factory settings
        if self.firmware_version >= 7:
            self._write(self.ID,' FACTORY RESTORE ALL')
            time.sleep(2)
            self._flush()
        else:
            self.write(self.ID,'$$W5683=128')
            self.write(self.ID,'Z')
            time.sleep(2)
            self._flush()


# In[6]:


class PressureController(PressureMeter):
    """Controller class which extends the functionality of the MassFlowMeter class with options for control
    loop tuning, setpoint ramping, and control variable switching. Initialization is still slow due to the
    parent class initialization."""

    def __init__(self, ID :str ='A', port : str ='/dev/ttyUSB0', baud : int =19200, config = None):
        # Configure the device for scripted control and gathers further data about the device
        # Future release may include config file loading to accelerate this step
        super().__init__(ID, port, baud, config)
        if not config:
            self.variables['setpoint_changes'] = 0


    def _eeprom_saving(self, read: bool = False, state: bool = False):
        # Enables or diables EEPROM saving for setpoint
        r18 = int(self._write(self.ID,'$$R18',True)[0].split()[3])

        if read:
            self.variables['ram_only_setpoint'] = 0 if (r18 & 32768) else 1
            return

        if not state and (r18 & 32768):
            r18 -= 32768
        elif state and not (r18 & 32768):
            r18 += 32768

        self._write(self.ID,f'$$W=18{r18}')
        self._eeprom_saving(read=True)


    def set_setpoint(self, setpoint: float = 0):
        # Takes a setpoint in floating point value and commands device with it
        # GP devices only accepted integer counts of fullscale so a conversion is done
        self._write(self.ID, f'S{setpoint}')
        self._flush()
        self.variables['setpoint_changes'] += 1
        if self.variables['setpoint_changes'] > 100000 and not self.variables['ram_only_setpoint']:
            self._eeprom_saving()


    def valve_hold_closed(self):
        # Holds the valves closed
        self._write(self.ID,'$$HC')


    def valve_hold(self):
        # Holds the valves at the current position
        self._write(self.ID,'$$HP')


    def valve_exhaust(self):
        # Holds exhaust valve open and closes inlet valve
        self._write(self.ID,'$$E')


    def cancel_hold(self):
        # Cancels hold and resumes active control
        self._write(self.ID,'$$C')


    def pid(self, P=0, I=0, D=0, read=True):
        # Sets or returns PID gains
        if read:
            pid = {}
            pid['P'] = int(self._write(self.ID,'$$R21',True)[0].split()[3])
            pid['D'] = int(self._write(self.ID,'$$R22',True)[0].split()[3])
            pid['I'] = int(self._write(self.ID,'$$R23',True)[0].split()[3])
            pid['Loop'] = self.pid_loop(read=True)
            return pid

        self._write(self.ID,f'$$W21={P}')
        time.sleep(1)
        self._write(self.ID,f'$$W22={D}')
        time.sleep(1)
        self._write(self.ID,f'$$W23={I}')


    def pid_loop(self, loop = 0, read = False, verbose = False):
        # Sets or reads the control loop type of the device
        loops = {0: 'PDF', 1: 'PD2I'}

        # Reads out the loop type
        if read:
            val = int(self._write(self.ID, '$$R85', True)[0].split()[3])
            loop = 0 if (val == 0 or val == 1) else 1
            return loops[loop]

        # Loop information stored in register 85
        val = int(self._write(self.ID,'R85',True)[0].split()[3])
        if loop == ('PDF' or 0):
            val = 0
            self.variables['current_loop'] = 'PDF'
        elif loop == ('PDDI' or 'PD2I' or 1):
            val = 32770 if val > 2 else 2
            self.variables['current_loop'] = 'PDDI'
        else:
            pass
        self._write(self.ID,f'W85={val}')

        # Optional print out of the change
        if verbose:
            print(f'The control loop has been set to {loops[loop]}')


    def setpoint_ramp(self, step_size=0, timedelta=0):
        # Creates a limit to the setpoint increase as a function of time allowing
        # slower adjustments outside of the PID domain
        if isinstance(self.firmware_version,str) or self.firmware_version < 8:
            raise Exception('This function is not available for units with firmware earlier than 8v.')
        step = step_size * 64000 // self.variables['fullscale']
        self._write(self.ID,f'$$W160={step}')
        time.sleep(1)
        self._write(self.ID,f'$$W161={timedelta}')


    def set_autotare(self, delay):
        # Sets the power-up and auto tare time delay. A value of zero disables them.
        r18 = int(self._write(self.ID,'$$R18',True)[0].split()[3])
        old = r18 & 255
        new = r18 - old + delay
        self._write(self.ID,f'$$W18={new}')
        r19 = int(self._write(self.ID,'$$R19',True)[0].split()[3])
        r20 = int(self._write(self.ID,'$$R20',True)[0].split()[3])
        old = r19 & 255

        # Auto Tare is enabled/disabled through register 20 but configured through 19
        if delay > 0:
            self._write(self.ID,f'$$W20={r20 + 8192 - (r20 & 8192)}')
            new = r19 - old + delay
            self._write(self.ID,f'$$W19={new}')
        else:
            self._write(self.ID,f'$$W20{r20 - (r20 & 8192)}')


    def powerup_setpoint(self, setpoint):
        # Enables a power-up setpoint for the device

        r18 = int(self._write(self.ID,'$$R18',True)[0].split()[3])

        if self.variables['ram_only_setpoint']:
            # Temporarily enable EEPROM saving
            r18 += 32768
            self._write(self.ID,f'$$W18={r18}')
            self._flush()
            time.sleep(1)

        # Write new setpoint to save in EEPROM
        self.set_setpoint(setpoint)
        time.sleep(1)

        # Disable saving with new setpoint stored
        r18 = r18 - 32768
        self._write(self.ID,f'$$W18={r18}')
        self._flush()


    def setpoint_limits(self, minimum, maximum):
        # Limit the acceptable setpoints the controller will use
        if (isinstance(self.firmware_version,str) or self.firmware_version < 8):
            raise Exception('This function is not available for units with firmware earlier than 8v.')
        fullscale = variables['fullscale']
        # Convert and write minimum and maximum values as device counts
        if minimum:
            self._write(self.ID,f'W169={minimum * 64000 / fullscale}')
            time.sleep(1)
        if maximum:
            self._write(self.ID,f'W170={maximum * 64000 / fullscale}')


# In[7]:


def config_generator(device, filename: str = None, path: str = None):

    import os

    absolute_path = os.path.abspath('')
    relative_path = 'deviceconfigs'
    path = os.path.join(absolute_path, relative_path)

    if not os.path.isdir('deviceconfigs'):
        os.mkdir(path)


    if not filename:
        filename = str(device) + '_config.txt'


    cur_path = os.getcwd()
    os.chdir(path)

    with open(filename,'wb') as f:
        pickle.dump(device.variables, f)

    os.chdir(cur_path)

