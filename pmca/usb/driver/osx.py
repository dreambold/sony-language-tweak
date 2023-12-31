"""Uses Sony kexts to communicate with mass storage cameras"""
# The SONYDeviceType01 kext is included in the DriverLoader application
# The SONYDeviceType04 kext is included in the PMCADownloader plugin

from ctypes import *
from ctypes.util import *
import os

from . import *

iokit = cdll.LoadLibrary(find_library('IOKit'))
cf = cdll.LoadLibrary(find_library('CoreFoundation'))

kIOMasterPortDefault = c_void_p.in_dll(iokit, 'kIOMasterPortDefault')

kSCSIDataTransfer_NoDataTransfer = 0
kSCSIDataTransfer_FromInitiatorToTarget = 1
kSCSIDataTransfer_FromTargetToInitiator = 2

iokit.mach_task_self.argtypes = []
iokit.mach_task_self.restype = c_void_p

iokit.IOServiceMatching.argtypes = [c_char_p]
iokit.IOServiceMatching.restype = c_void_p

iokit.IOServiceGetMatchingServices.argtypes = [c_void_p, c_void_p, c_void_p]
iokit.IOServiceGetMatchingServices.restype = c_void_p

iokit.IORegistryEntryGetParentEntry.argtypes = [c_void_p, c_char_p, c_void_p]
iokit.IORegistryEntryGetParentEntry.restype = c_uint

iokit.IORegistryEntryCreateCFProperty.argtypes = [c_void_p, c_void_p, c_void_p, c_uint]
iokit.IORegistryEntryCreateCFProperty.restype = c_void_p

iokit.IOObjectRelease.argtypes = [c_void_p]
iokit.IOObjectRelease.restype = c_uint

iokit.IOObjectConformsTo.argtypes = [c_void_p, c_char_p]
iokit.IOObjectConformsTo.restype = c_uint

iokit.IOServiceOpen.argtypes = [c_void_p, c_void_p, c_int, c_void_p]
iokit.IOServiceOpen.restype = c_uint

iokit.IOServiceClose.argtypes = [c_void_p]
iokit.IOServiceClose.restype = c_uint

iokit.IOConnectCallScalarMethod.argtypes = [c_void_p, c_uint, c_void_p, c_uint, c_void_p, c_void_p]
iokit.IOConnectCallScalarMethod.restype = c_uint

iokit.IOConnectCallStructMethod.argtypes = [c_void_p, c_uint, c_void_p, c_size_t, c_void_p, c_void_p]
iokit.IOConnectCallStructMethod.restype = c_uint

iokit.KextManagerCopyLoadedKextInfo.argtypes = [c_void_p, c_void_p]
iokit.KextManagerCopyLoadedKextInfo.restype = c_void_p

cf.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, c_uint]
cf.CFStringCreateWithCString.restype = c_void_p

cf.CFNumberGetValue.argtypes = [c_void_p, c_int, c_void_p]
cf.CFNumberGetValue.restype = c_void_p

cf.CFDictionaryContainsKey.argtypes = [c_void_p, c_void_p]
cf.CFDictionaryContainsKey.restype = c_bool

cf.CFRelease.argtypes = [c_void_p]
cf.CFRelease.restype = None

kextNames = {
 'SONYDeviceType01': b'com.sony.driver.dsccamFirmwareUpdaterType00',
 'SONYDeviceType04': b'com.sony.driver.dsccamDeviceInfo00',
}
kextOpenUserClient = 0
kextCloseUserClient = 1
kextSendMemoryBlock = 6
kextErrorDeviceBusy = 0xE00002D8

class SCSI_COMMAND_DESC_MEMORYBLOCK(Structure):
 _fields_ = [
  ('cbd', 16 * c_ubyte),
  ('cbdSize', c_uint),
  ('direction', c_uint),
  ('timeout', c_uint),
  ('unknown1', c_uint),
  ('bufferSize', c_uint),
  ('unknown2', c_uint),
  ('buffer', POINTER(c_ubyte)),
 ]


class MscContext(BaseUsbContext):
 def __init__(self):
  super(MscContext, self).__init__('OS-X-MSC', USB_CLASS_MSC)

 def listDevices(self, vendor):
  return _listDevices(vendor)

 def openDevice(self, device):
  return _MscDriver(device.handle)


def isMscDriverAvailable():
 return _isKextLoaded() or _isKextInstalled()


def _isKextInstalled():
 for name in kextNames.keys():
  if os.path.exists('/Library/Extensions/%s.kext/Contents/Info.plist' % name):
   return True
 return False

def _isKextLoaded():
 loaded = False
 infos = iokit.KextManagerCopyLoadedKextInfo(0, 0)

 for name in kextNames.values():
  key = cf.CFStringCreateWithCString(0, name, 0)
  if cf.CFDictionaryContainsKey(infos, key):
   loaded = True
  cf.CFRelease(key)

 cf.CFRelease(infos)
 return loaded

def _getParent(device, parentType):
 while not iokit.IOObjectConformsTo(device, parentType):
  parent = c_void_p()
  res = iokit.IORegistryEntryGetParentEntry(device, b'IOService', byref(parent))
  if res:
   return None
  device = parent
 return device

def _getProperty(device, prop):
 key = cf.CFStringCreateWithCString(0, prop, 0)
 container = iokit.IORegistryEntryCreateCFProperty(device, key, 0, 0)
 cf.CFRelease(key)
 if container:
  number = c_uint16()
  cf.CFNumberGetValue(container, 2, byref(number))
  cf.CFRelease(container)
  return number.value

def _listDevices(vendor):
 # Similar to pyserial: https://github.com/pyserial/pyserial/blob/master/serial/tools/list_ports_osx.py
 itr = c_void_p()
 iokit.IOServiceGetMatchingServices(kIOMasterPortDefault, iokit.IOServiceMatching(b'IOBlockStorageServices'), byref(itr))
 devices = set()
 while True:
  service = iokit.IOIteratorNext(itr)
  if not service:
   break
  device = _getParent(service, b'IOUSBDevice')
  for kextName in kextNames.values():
   driver = _getParent(service, kextName.replace(b'.', b'_'))
   if device and driver and device.value not in devices:
    devices.add(device.value)
    vid = _getProperty(device, b'idVendor')
    pid = _getProperty(device, b'idProduct')
    if vid == vendor:
     yield UsbDeviceHandle(driver, vid, pid)
 iokit.IOObjectRelease(itr)


class _MscDriver(BaseMscDriver):
 def __init__(self, device):
  self.dev = c_void_p()
  res = iokit.IOServiceOpen(device, iokit.mach_task_self(), 0, byref(self.dev))
  if res:
   raise Exception('IOServiceOpen failed')
  res = iokit.IOConnectCallScalarMethod(self.dev, kextOpenUserClient, 0, 0, 0, 0)
  if res:
   raise Exception('OpenUserClient failed')

 def __del__(self):
  iokit.IOConnectCallScalarMethod(self.dev, kextCloseUserClient, 0, 0, 0, 0)
  iokit.IOServiceClose(self.dev)

 def _send(self, cbd, direction, buffer):
  desc = SCSI_COMMAND_DESC_MEMORYBLOCK(
   cbd = (c_ubyte * 16).from_buffer_copy(cbd.ljust(16, b'\0')),
   cbdSize = len(cbd),
   direction = direction,
   timeout = 60000,
   bufferSize = len(buffer),
   buffer = buffer,
  )
  descSize = c_size_t(sizeof(SCSI_COMMAND_DESC_MEMORYBLOCK))
  output = create_string_buffer(512)
  outputSize = c_size_t(512)

  res = iokit.IOConnectCallStructMethod(self.dev, kextSendMemoryBlock, byref(desc), descSize, byref(output), byref(outputSize))

  if res == 0:
   return MSC_SENSE_OK
  elif res == kextErrorDeviceBusy:
   return 0x9, 0x81, 0x81
  else:
   return MSC_SENSE_ERROR_UNKNOWN

 def sendCommand(self, command):
  buffer = (c_ubyte * 0)()
  return self._send(command, kSCSIDataTransfer_NoDataTransfer, buffer)

 def sendWriteCommand(self, command, data):
  buffer = (c_ubyte * len(data)).from_buffer_copy(data)
  return self._send(command, kSCSIDataTransfer_FromInitiatorToTarget, buffer)

 def sendReadCommand(self, command, size):
  buffer = (c_ubyte * size)()
  sense = self._send(command, kSCSIDataTransfer_FromTargetToInitiator, buffer)
  return sense, bytes(bytearray(buffer))
