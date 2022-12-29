import board
import digitalio
import storage
 # Set the storage to be writeable by circuitpython, in order to edit the HTML
 # To load the program to be writeable by the computer, simply hold the "up" button during the boot process

switch = digitalio.DigitalInOut(board.TX)
storage.remount("/", not switch.value)