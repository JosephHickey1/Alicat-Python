#!/usr/bin/env python
# coding: utf-8

# These classes form the backbone of Alicat operations through serial commmands

try:
    import serial
except ImportError:
    print("An error occurred while attempting to import the pyserial backend. Please check your installation and try again.")

class Serial_Connection(object):
    """The serial connection object from which other classes inherit port and baud settings as
    well as reading and writing capabilities. Preprocessing for GP firmware outputs is performed
    using the remove_characters function"""
    
    # A dictionary storing open serial ports for comparison with new connections being opened
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
    


class MassFlowMeter(Serial_Connection):
    """Base laminar dP mass flow object which contains all functions specific to mass flow devices.
    Initial creation of the object is slow as many characteristics are retrieved and parsed.
    Future versions may allow the passing of a config file to initialize settings."""
    
    def __init__(self, ID :str ='A', port : str ='/dev/ttyUSB0', baud : int =19200):
        # Initialize a serial connection for commuication with the device
        super().__init__(port, baud)
        self.ID, self.port, self.baud = ID, port, baud
        
        # Gather device information and specific formatting for data
        self._fetch_gas_list()
        self._fetch_firmware_version()
        self._data_format()
        self.current_gas = self._write(self.ID,'',True)[-1].split()[-1]
        
        # Disable EEPROM gas selection saving as a safety precaution
        r18 = int(self._write(self.ID,'$$R18',True)[0].split()[3])
        if not (r18 & 2048):
            r18 += 2048
            self._write(self.ID,f'$$W18={r18}')
        
    
    def _fetch_gas_list(self):
        # Empty dictionaries to store gas and index information
        self.gas_list = {}
        self.gas_ref = {}
        self.reverse_gas_list = {}
        
        # Query gas table for index and short name
        gases = [i.split() for i in self._write(self.ID, '??G*',True)]
        
        # Save gas data in dictionaries
        for i in range(len(gases)):
            self.gas_list[gases[i][2]] = int(gases[i][1][1:])
            self.gas_ref[int(gases[i][1][1:])] = int(gases[i][1][1:])
            self.reverse_gas_list[int(gases[i][1][1:])] = gases[i][2]
            self.gas_ref.update(self.gas_list)
        del gases
        
    
    def _fetch_firmware_version(self):
        # Query manufacturer data saving only the firmwar version
        self.manufacturer_data = [i.split() for i in self._write(self.ID, '??M*',True)]
        self.firmware_version = self.manufacturer_data[-1][-1]
        
        # Early firmware version would present the version with a capitalized 'V' between major and minor version
        if self.firmware_version[:2] != 'GP':
            self.firmware_version, self.firmware_minor = self.firmware_version.replace('V','v').split('v',1)
            self.firmware_version = int(self.firmware_version)
        else:
            # Safe to assume all GP units still functioning were of the 07 release
            self.firmware_version, self.firmware_minor = 'GP', '07'
        
        
    def _data_format(self):
        """Uses serial command for querying the format of general poll dataframe and parses the
        output based on firmware version to get a list of parameters being sent over serial and
        a readable list of parameter name and units"""
        self.data = []
        # Reads in format data for parsing
        outputs = [i.split() for i in self._write(self.ID,'??D*',True)]
        for i in range(len(outputs)):
            outputs[i][1] = outputs[i][1][1:]
        # Checks firmware version as the format of the format output changed with 7v firmware
        if isinstance(self.firmware_version, str) or (isinstance(self.firmware_version,int) and self.firmware_version < 6):
            # For 6v and older format
            self.ranges = {}
            for i in range(2, len(outputs)):
                c = outputs[i]
                if c[-1] == 'na' or c[-1] == '_':
                    del c[-1]
                # Appends parameter ID, Parameter Name, and Parameter Units for each parameter
                self.data.append([int(c[1]), c[2], c[-1]])
                self.ranges[c[2].lower()] = c[-2]
        
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
                self.data.append([output2[i][2], output2[i][3], output2[i][-1]])
        # Delete temporary arrays
            del output2
        del outputs
        # Generate keys for the `get` command
        self.keys = [self.data[i][1] for i in range(len(self.data))]
    
    
    def _print_dataframe(self,iterations=1):
        # Prints a number of lines of data from the device. Data is in the same order as self.data
        dataframe = []
        for i in range(iterations):
            dataframe.append(self._write(self.ID,'',True))
        return dataframe
        
        
    def get(self):
        # Returns a dictionary of current values bound to their parameter name
        data = self._write(self.ID,'',True)[0].split()[1:]
        values = {k: v for k,v in zip(self.keys, data)}
        return values
        
        
    def set_gas(self, gas):
        # Changes gas to the new gas selected taking either the short name or index
        if int(self.gas_ref[gas]) != int(self.gas_ref[self.current_gas]):
            self._write(self.ID,f'G$${self.gas_ref[gas]}',verbose)
            self.current_gas = self.reverse_gas_list[int(self.gas_ref[gas])]
        
        
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
            self._write(self.ID,'P')
        else:
            self._write(self.ID,'PC')
    
    
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
                    reg87 = int(self._write(self.ID,'R87', True)[0].split()[-1]) 
                    # Change to read_register call when implemented
                    if not int(bin(reg87)[-2]):
                        self._write(self.ID,f'W87={2+reg87}')
                idval = 256 * ord(self.ID)
                val = 16 + idval + bauds[newbaud]
                self._write(self.ID,f'W17={val}')
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
            # need to add unit checking and unit changing, also check against existing STP values
            temp = (standardtemp + 273.15) * 100000
            press = standardpress * 100000
            self._write(self.ID, f'W137={temp}')
            self._write(self.ID, f'W138={press}')
    
    
    def change_ntp(self, normaltemp, normalpress):
        # Change Normal Temperature and Pressure in units of Celsius and PSIA
        # Used for flow units starting with 'N' (NLPM, NCCM, Nin3/m, etc.)
        if self.firmware_version == 'GP':
            raise Exception('NTP modification is not available in this firmware version')
        else:
            # need to add unit checking and unit changing, also check against existing NTP values
            temp = (normaltemp + 273.15) * 100000
            press = normalpress * 100000
            self._write(self.ID, f'W139={temp}')
            self._write(self.ID, f'W140={press}')
    
    
    def set_alarm(self, expression: str = ''):
        # Sets a new alarm using the set and clear expressions in RPN
        # Configuration info can be found at: https://www.alicat.com/using-your-alicat/alarm-function-ale-command-tutorial/
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
            self.write(self.ID,'W5683=128')
            self.write(self.ID,'Z')
            time.sleep(10)
            self._flush()
        


class MassFlowController(MassFlowMeter):
    """Controller class which extends the functionality of the MassFlowMeter class with options for control
    loop tuning, setpoint ramping, and control variable switching. Initialization is still slow due to the
    parent class initialization."""
    
    def __init__(self, ID :str ='A', port : str ='/dev/ttyUSB0', baud : int =19200):
        # Configure the device for scripted control and gathers further data about the device
        # Future release may include config file loading to accelerate this step
        super().__init__(ID, port, baud)
        self.ID, self.port, self.baud = ID, port, baud
        # Full scale calculations may be moved to the MassFlowMeter class since it is a shared property
        self.mfullscale = self._get_fullscale('mass')
        self.pfullscale = self._get_fullscale('pressure')
        self.vfullscale = self._get_fullscale('volumetric')
        self.scales = {'mass': self.mfullscale, 'volumetric': self.vfullscale, 'volume': self.vfullscale,                        'pressure': self.pfullscale}
        self.variables = {1024: 'mass', 768: 'volumetric', 256: 'pressure'}
        self.change_control_var('mass')
        
        # Disables EEPROM saving of setpoints for safety
        r18 = int(self._write(self.ID,'$$R18',True)[0].split()[3])
        if r18 & 32768:
            r18 -= 32768
            self._write(self.ID,f'$$W18={r18}')
        
        
        
    def set_setpoint(self, setpoint: float = 0):
        # Takes a setpoint in floating point value and commands device with it
        # GP devices only accepted integer counts of fullscale so a conversion is done
        if self.firmware_version == 'GP' or self.firmware_version < 6:
            setpoint = str(int(64000 * setpoint // self.fullscale))
            self._write(self.ID, setpoint)
        else:
            self._write(self.ID, f'S{setpoint}')
        self.setpoint = setpoint
    
    
    def _get_fullscale(self, statistic = 'mass'):
        # Determines fullscale of each statistic in current engineering units
        # May be moved due to shared properties with MassFlowMeter
        exch = {'mass' : 5, 'volumetric': 4, 'pressure': 2}
        if isinstance(self.firmware_version, str) or self.firmware_version < 6:
            return float(self.ranges[statistic])
        else:
            response = self._write(self.ID, f'FPF {exch[statistic]}', True)
            return float(response[0].split()[1])
    
    
    def set_batch(self, batchsize):
        # Sets the size of a single batch and resets the totalizer
        # Subsequent batches can be reset using the <Object>.totalizer_reset() method
        if self.firmware_version == 'GP':
            return 'This function is not available for units with GP firmware.'
        self.totalizer_reset()
        self._write(self.ID,f'$$W93={batchsize}')

        
    def valve_hold(self):
        # Holds the valve at the current position
        self._write(self.ID,'$$H')
    
    
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
        self._write(self.ID,f'$$W22={D}')
        self._write(self.ID,f'$$W23={I}')

            
    def pid_loop(self, loop, read = True, verbose = False):
        # Sets or reads the control loop type of the device
        loops = {0: 'PDF', 1: 'PD2I'}
        
        # Determines where loop type information is stored
        if read:
            addr = 23 if self.firmware_version == 'GP' else 85
            val = int(self._write(self.ID, '$$R{addr}', True)[0].split()[3])
            if addr == 23 and (val & 1):
                loop = 1 if (val & 1) else 0
            else:
                loop = 0 if (val == 0 or val == 1) else 1
            return loops[loop]
        
        # GP units used the least significant bit to determine loop type 
        if self.firmware_version == 'GP':
            val = int(self._write(self.ID, '$$R23', True)[0].split()[3])
            self.current_loop = 1 if val & 1 else 0
            if read:
                print(f'The current control loop is set to {self.loops[loop]}')

            if loop == 'PDF' and self.current_loop != 0:
                val -= 1
                self._write(self.ID,f'$$W23={val}')
                self.current_loop = 0
            elif (loop == 'PDDI' or loop == 'PD2I') and self.current_loop != 1:
                val += 1
                self._write(self.ID,f'$$W23={val}')
                self.current_loop = 1
            else:
                pass
        # Modern units differentiate between single and dual valve devices
        else:
            val = int(self._write(self.ID,'R85',True)[0].split()[3])
            if loop == ('PDF' or 0):
                val = 0
            elif loop == ('PDDI' or 'PD2I' or 1):
                val = 32770 if val > 2 else 2
            else:
                pass
            self._write(self.ID,f'W85={val}')
        
        # Optional print out of the change
        if verbose:
            print(f'The control loop has been set to {loops[self.current_loop]}')
        
    
    def change_control_var(self, variable = 'mass'):
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
        
        if var != loop[variable]:
            reg = reg - var + loop[variable]
            self._write(self.ID,f'$$W20={reg}')
        
        # Changes loop variable property and which fullscale is used
        self.control_variable = loop[variable]
        self.fullscale = self.scales[variable]
    
    
    def setpoint_ramp(self, step_size=0, timedelta=0):
        # Creates a limit to the setpoint increase as a function of time allowing
        # slower adjustments outside of the PID domain
        if isinstance(self.firmware_version,str) or self.firmware_version < 8:
            return 'This feature is not available for units with firmware earlier than 8v'
        step = step_size * 64000 / self.mfullscale
        self._write(self.ID,f'$$W160={step}')
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
        
        # Temporarily enable EEPROM saving
        r18 = int(self._write(self.ID,'$$R18',True)[0].split()[3]) + 32768
        self._write(self.ID,f'$$W18={r18}')
        
        # Write new setpoint to save in EEPROM
        self.set_setpoint(setpoint)
        
        # Disable saving with new setpoint stored
        r18 -= 32768
        self._write(self.ID,f'$$W18={r18}')
        

    def setpoint_limits(self, minimum, maximum):
        # Limit the acceptable setpoints the controller will use
        if (isinstance(self.firmware_version,str) or self.firmware_version < 8):
            return 'This feature is not available for units with firmware earlier than 8v'
        
        # Convert and write minimum and maximum values as device counts
        if minimum:
            self._write(self.ID,f'W169={minimum * 64000 / self.fullscale}')
        if maximum:
            self._write(self.ID,f'W170={maximum * 64000 / self.fullscale}')

    def flow_limit(self, limit):
        # Sets a limit to the flow rate while in pressure control mode
        # If controlling on pressure and totalizing flow, this should be set <= self.mfullscale
        if (isinstance(self.firmware_version,str) or self.firmware_version < 8):
            return 'This feature is not available for units with firmware earlier than 8v'
        self._write(self.ID,f'W165={limit * 64000 / self.mfullscale}')
        
        
    def control_deadband(self, deadband):
        # Set a custom deadband in device units which the control algortihm considers
        # the reading and setpoint to be equivalent. Used for increased system stability.
        self._write(self.ID,f'$$W58={deadband * 64000 / self.fullscale}')
        

    def overpressure_limit(self, limit):
        # Set a limit in device units for pressure which upon reaching, the valve will close
        # Send a new setpoint command to resume active control
        self._write(Self.ID,f'$$W73{limit * 64000 / self.pfullscale}')

