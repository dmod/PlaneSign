import sys
import dbus, dbus.mainloop.glib
import subprocess
from gi.repository import GLib
from gatt import Application, Advertisement, Service, Characteristic
from gatt import find_adapter, register_app_cb, register_app_error_cb, register_ad_cb, register_ad_error_cb

class WifiSetService(Service):

    def __init__(self, index,main_loop):
        self.mgr = WifiManager()
        self.AP_list = []  #msg: signal|locked|in_supplicant|conected|SSID
        self.notifications=[]
        self.current_requested_ssid = ''
        self.current_requested_pw = ''
        self.main_loop = main_loop
        Service.__init__(self, index, UUID_WIFISET, True)
        self.add_characteristic(WifiDataCharacteristic(0,self))


    def register_SSID(self,val):
        ''' action taken when ios app writes to WifiData characteristic
        val is in the form [first_string,second_string, code] - see description in characteristic Write method
        ios sends either commands or request for connections to SSID:
            - commands: val[0] must be blank string. then val[1] contains the command
            - connection_request: val[0] must not be blank and is the requested SSID
                                  val[1] is the password - which can be left blank
        Notifications to ios are one of three 
            (all notifications will be pre-pended by SEPARATOR in notification callback "info_wifi_callback"  below as means 
             to differentiate notification from AP info read by ios)
            - READY: when list of requested AP is compiled and ready to be sent
            - AP.msg: in the form xxxxSSID - where x is integer - indicated connected ssid
            - FAIL: if a connection request resulted in the RPi not being able to connect to any wifi AP
                    note: if a requested SSID could not be connected to, but RPi was able to reconnect to previous AP,
                          the connected AP info is sent back - it is up to ios to recognized that the requested connection has failed
                          and RPi is still connected to the previous AP.'''
        mLOG.log(f'received from iphone: registering SSID {val}')
        #string sent must be SSID=xxxPW=yyy where xxx is the SSID and yyy is password
        #PW+ maybe omited
        if val[0] == '':  #this means we received a request from ios (started with SEP)
            if val[1] == 'OFF':
                #call wifiwpa method to disconnect from current ssid
                self.mgr.wifi_connect(False)
            elif val[1] == 'ON':
                self.mgr.wifi_connect(True)
            elif val[1] == 'DISCONN':
                self.mgr.disconnect()
            elif val[1] == 'APs':
                #mLOG.log('getting list')
                returned_list = self.mgr.get_list() #go get the list
                self.AP_list = []
                for ap in returned_list:
                    self.AP_list.append(ap.msg())
                self.notifications.append('READY')
                mLOG.log(f'READY: AP List for ios: {self.AP_list}')
            else:
                #may need to notify?
                mLOG.log(f'Invalid SSID string {val}')
                return
        else:
            mLOG.log(f'received requested SSID for connection: {val}')
            self.current_requested_ssid = val[0]
            self.current_requested_pw = val[1]
            network_num = -1
            #if user is connecting to an existing network - only the SSID is passed (no password) 
            #   so network number is unknown (-1)
            if self.current_requested_ssid:
                mLOG.log(f'about to connect to ssid:{self.current_requested_ssid}, with password:{self.current_requested_pw}')
                connected_ssid = self.mgr.request_connection(self.current_requested_ssid,self.current_requested_pw)
                if len(connected_ssid)>0:
                    mLOG.log(f'adding {connected_ssid} to notifications')
                    self.notifications.append(connected_ssid)
                else:
                    mLOG.log(f'adding FAIL to notifications')
                    self.notifications.append('FAIL')


class WifiDataCharacteristic(Characteristic):

    def __init__(self, index,service):
        self.notifying = False
        self.last_notification = -1
        Characteristic.__init__(self, index,UUID_WIFIDATA,["notify", "read","write"], service)
        self.add_descriptor(InfoWifiDescriptor(0,self))
        self.mainloop = service.main_loop


    def info_wifi_callback(self):
        '''mainloop checks here to see if there is something to "notify" iphone app
        note: ios expects to see the SEPARATOR prefixed to notification - otherwise notification is discarded'''
        if self.notifying:
            if len(self.service.notifications)>0:
                mLOG.log(f'in notification: {self.service.notifications}')
                strtemp = SEPARATOR + self.service.notifications.pop(0)
                value=[]
                for c in strtemp:
                    value.append(dbus.Byte(c.encode()))
                self.PropertiesChanged("org.bluez.GattCharacteristic1", {"Value": value}, [])
                mLOG.log('notification sent')
        return self.notifying

    def StartNotify(self):
        mLOG.log(f'ios has started notifications for wifi info')
        if self.notifying:
            return
        self.notifying = True
        self.add_timeout(NOTIFY_TIMEOUT, self.info_wifi_callback)

    def StopNotify(self):
        self.notifying = False

    def ReadValue(self, options):
        #ios will read list of ap messages until empty
        value = []
        msg = SEPARATOR+'EMPTY' #ios looks for separator followed by empty to indicate list is over (EMPTY could be an ssid name...)
        #mLOG.log(f'ios reading from {self.service.AP_list}')  
        if len(self.service.AP_list)>0:
            msg = self.service.AP_list.pop(0)
        for c in msg:
            value.append(dbus.Byte(c.encode()))
        mLOG.log(f'ios is reading AP msg: {msg}')
        return value

    def WriteValue(self, value, options):
        #this is called by Bluez when the clients writes a value to the server (RPI)
        """
        messages are either:
             - SEP + command (for controling wifi on pi or asking for AP list)
             - ssid + SEP  (no paswword)
             - ssid + SEP + password + SEP + code    code = CP: call change_password; =AD: call add_network
        returns [first_string,second_string]
        everything that arrives before SEP goes into first_string
        everything that arrives after SEP goes into second string
        for requests:  first_string is empty and request is in second string
        if first_string is not empty: then it is an SSID for connection 
            which may or may not have a password in second string
        """
        received=['','']
        index = 0
        for val in value:
            if val == dbus.Byte(SEPARATOR_HEX):
                index += 1
            else:
                received[index]+=str(val)
        mLOG.log(f'from iphone received SSID/PW: {received}')
        ConfigData.reset_timeout()  # any data received from iphone resets the BLE Server timeout
        self.service.register_SSID(received)

class InfoWifiDescriptor(Descriptor):
    INFO_WIFI_DESCRIPTOR_UUID = "2901"
    INFO_WIFI_DESCRIPTOR_VALUE = "AP-List, Status, write:SSID=xxxPW=yyy"

    def __init__(self, index, characteristic):
        Descriptor.__init__(
                self, index, self.INFO_WIFI_DESCRIPTOR_UUID,
                ["read"],
                characteristic)

    def ReadValue(self, options):
        value = []
        desc = self.INFO_WIFI_DESCRIPTOR_VALUE

        for c in desc:
            value.append(dbus.Byte(c.encode()))
        return value



def graceful_quit(signum,frame):
    mLOG.log("stopping main loop on SIGTERM received")
    sleep(0.5)
    mainloop.quit()

def check_button():
    #placeholder -  return true if button was pressed
    return True

def timeout_manager():
    #mLOG.log(f'checking timeout {ConfigData.START}')
    if ConfigData.check_timeout():
        mLOG.log("BLE Server timeout - exiting...")
        sleep(0.2)
        mainloop.quit()
        return False
    else:
        return True