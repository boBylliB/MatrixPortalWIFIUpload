# SPDX-FileCopyrightText: 2019 ladyada for Adafruit Industries
# SPDX-License-Identifier: MIT

import board
import time
import busio
import os
from digitalio import DigitalInOut
from io import StringIO
import adafruit_requests as requests
import adafruit_esp32spi.adafruit_esp32spi_socket as socket
import adafruit_esp32spi.adafruit_esp32spi_wsgiserver as server
from adafruit_esp32spi import adafruit_esp32spi
from adafruit_wsgi.wsgi_app import WSGIApp

# Get wifi details and more from a secrets.py file
try:
    from secrets import secrets
except ImportError:
    print("WiFi secrets are kept in secrets.py, please add them there!")
    raise

print("Matrix Portal WIFI Client and Webserver")

TEXT_URL = "http://wifitest.adafruit.com/testwifi/index.html"
HOST_HTML = "web/index.html"
HOST_JS = "web/scripts/main.js"
FILENAMES = "filenames.txt"

# If you are using a board with pre-defined ESP32 Pins:
esp32_cs = DigitalInOut(board.ESP_CS)
esp32_ready = DigitalInOut(board.ESP_BUSY)
esp32_reset = DigitalInOut(board.ESP_RESET)

dev_pin = DigitalInOut(board.TX)

# If you have an AirLift Shield:
# esp32_cs = DigitalInOut(board.D10)
# esp32_ready = DigitalInOut(board.D7)
# esp32_reset = DigitalInOut(board.D5)

# If you have an AirLift Featherwing or ItsyBitsy Airlift:
# esp32_cs = DigitalInOut(board.D13)
# esp32_ready = DigitalInOut(board.D11)
# esp32_reset = DigitalInOut(board.D12)

# If you have an externally connected ESP32:
# NOTE: You may need to change the pins to reflect your wiring
# esp32_cs = DigitalInOut(board.D9)
# esp32_ready = DigitalInOut(board.D10)
# esp32_reset = DigitalInOut(board.D5)

spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)

requests.set_socket(socket, esp)

if esp.status == adafruit_esp32spi.WL_IDLE_STATUS:
    print("ESP32 found and in idle mode")
print("Firmware vers.", esp.firmware_version)
print("MAC addr:", [hex(i) for i in esp.MAC_address])

for ap in esp.scan_networks():
    print("\t%s\t\tRSSI: %d" % (str(ap["ssid"], "utf-8"), ap["rssi"]))

print("Connecting to AP...")
while not esp.is_connected:
    try:
        esp.connect_AP(secrets["ssid"], secrets["password"])
    except OSError as e:
        print("could not connect to AP, retrying: ", e)
        continue
print("Connected to", str(esp.ssid, "utf-8"), "\tRSSI:", esp.rssi)
print("My IP address is", esp.pretty_ip(esp.ip_address))
print(
    "IP lookup adafruit.com: %s" % esp.pretty_ip(esp.get_host_by_name("adafruit.com"))
)
print("Ping google.com: %d ms" % esp.ping("google.com"))

# esp._debug = True
print("Fetching text from", TEXT_URL)
r = requests.get(TEXT_URL)
print("-" * 40)
print(r.text)
print("-" * 40)
r.close()

# Relevant datastructures
filenames = []
queueData = ""
editQueue = []
editQueueChanged = False
uploadQueue = []
uploadQueueChanged = False

# Helper functions for display



# Helper functions for webserver

def rotateFilenames():
    filenames.append(filenames[0])
    filenames.pop[0]

def validIdx(idx, array):
    return (idx >= 0 and idx < len(array))

def removeFilename(targetIdx):
    if validIdx(targetIdx, filenames):
        os.remove("uploads/" + filenames[targetIdx])
        filenames.pop(targetIdx)

def swapFilenames(origin, target):
    if validIdx(origin, filenames) and validIdx(target, filenames):
        temp = filenames[target]
        filenames[target] = filenames[origin]
        filenames[origin] = temp

def shiftFilename(target, shift):
    bufferLow = target * -1
    bufferHigh = len(filenames) - target - 1

    if target < 0 or target > (len(filenames) - 1):
        target = len(filenames) - 1
    while shift > bufferHigh:
        shift -= len(filenames)
    while shift < bufferLow:
        shift += len(filenames)

    swapFilenames(target, target + shift)

def loadFilenames():
    try:
        with open(FILENAMES, 'r') as file:
            count = 0
            for line in file:
                if len(line) < 1:
                    continue
                filenames.append(line.strip())
                count += 1
    except OSError as e:
        print("Failure loading from file", FILENAMES, "due to: ", e)

def saveFilenames():
    with open(FILENAMES, 'w') as file:
        for line in filenames:
            file.write(line + '\n')

def updateHTML():
    with open(HOST_HTML, 'r') as file:
        currentHTML = file.read()
    HTMLData = currentHTML.split("<!--DATA-->")
    newHTML = HTMLData[0] + str("<!--DATA-->\n")
    count = 0
    for name in filenames:
        newHTML += "<input type=\"radio\" id=\"file:" + name + "\" name=\"filename\" value=\"" + name + "\">\n"
        newHTML += "<label for=\"file:" + name + "\">"
        if count == 0:
            newHTML += "NEXT: "
        else:
            newHTML += str(count) + " away: "
        newHTML += name + "</label><br>\n"
        count += 1
    newHTML += str("<!--DATA-->") + HTMLData[2]
    with open(HOST_HTML, 'w') as file:
        file.write(newHTML)

def updateQueueData():
    global queueData

    count = 0
    queueData = ""
    for name in filenames:
        queueData += "<input type=\"radio\" id=\"file:" + name + "\" name=\"filename\" value=\"" + name + "\">\n"
        queueData += "<label for=\"file:" + name + "\">"
        if count == 0:
            queueData += "NEXT: "
        else:
            queueData += str(count) + " away: "
        queueData += name + "</label><br>\n"
        count += 1

def getUpload():
    global uploadQueueChanged

    if len(uploadQueue) < 1:
        return

    for idx in range(len(uploadQueue)):
        upload = uploadQueue[idx]

        uploadData = upload.body.read().split('\n',3)
        print(uploadData)
        boundary = uploadData[0].strip()
        filename = uploadData[1].split('filename=')[1].split('"')[1]
        filedata = uploadData[3].strip().split('\n--' + boundary)[0]

        print("Filedata: ", filedata)
        print("Filename: ", filename)

        for jdx in range(len(filenames)):
            if filenames[jdx] == filename:
                print("Duplicate found, removing from list.")
                filenames.pop(jdx)

        try:
            with open('uploads/' + filename, 'w') as file:
                file.write(filedata)
        except UnicodeDecodeError as e:
            print("UnicodeDecodeError: ", e)
            print("Attempting to write to file in binary...")
            with open('uploads/' + filename, 'wb') as file:
                file.write(bytes(filedata))
        filenames.append(filename)

        uploadQueue.pop(idx)

    saveFilenames()
    updateHTML()
    updateQueueData()
    uploadQueueChanged = False

def handleEdit():
    global editQueueChanged

    if len(editQueue) < 1:
        return

    for idx in range(len(editQueue)):
        options = editQueue[idx]

        filename = ""
        action = ""

        for option in options:
            parameters = option.split("=")
            if parameters[0] == "filename":
                filename = parameters[1]
            elif parameters[0] == "action":
                action = parameters[1]

        targetIdx = -1
        for jdx in range(len(filenames)):
            if filenames[jdx] == filename:
                targetIdx = jdx

        if targetIdx == -1:
            print("Filename", filename, "not found in handleEdit()!")
            continue

        if action == "Move+Up":
            print("Shifting", filename, "up in the queue")
            shiftFilename(targetIdx, -1)
        elif action == "Move+Down":
            print("Shifting", filename, "down in the queue")
            shiftFilename(targetIdx, 1)
        elif action == "Delete":
            print("Deleting ", filename)
            removeFilename(targetIdx)
        elif action == "Clear+Queue":
            print("Clearing the Queue")
            while len(filenames) > 0:
                removeFilename(0)

        editQueue.pop(idx)

    saveFilenames()
    updateHTML()
    updateQueueData()
    editQueueChanged = False

# Here we create our application, registering the
# following functions to be called on specific HTTP GET requests routes

web_app = WSGIApp()

@web_app.route("/edit","POST")
def edit(request):
    global editQueueChanged
    formdata = request.body.read()
    print("Edit page request received of type: ", request.method)
    print("Received data: ", formdata)
    options = formdata.split("&")
    filename = ""
    action = ""
    for option in options:
        parameters = option.split("=")
        if parameters[0] == "filename":
            filename = parameters[1]
        elif parameters[0] == "action":
            action = parameters[1]
    targetIdx = -1
    for idx in range(len(filenames)):
        if filenames[idx] == filename:
            targetIdx = idx
    if targetIdx == -1 and not action == "Clear+Queue":
        print("Filename", filename, "not found!")
    else:
        editQueue.append(options)
        editQueueChanged = True
    return ("303 See Other", [], "<meta http-equiv=\"Refresh\" content=\"0; url=/\" />")

@web_app.route("/upload","POST")
def upload(request):
    global uploadQueueChanged
    print("Upload page request received of type: ", request.method)
    print("Received data: ", request.headers)
    uploadQueue.append(request)
    uploadQueueChanged = True
    return ("303 See Other", [], "<meta http-equiv=\"Refresh\" content=\"0; url=/\" />")

@web_app.route("/queueUpdate")
def updateQueue(request):
    global queueData
    print("Queue update request received of type: ", request.method)
    print("Queue update request headers: ", request.headers)
    return ("200 OK", [("Content-Type","text/plain")], queueData)

@web_app.route("/scripts/main.js")
def load_javascript(request):
    print("Javascript request received of type: ", request.method)
    print("Attempting to send JavaScript from: ", HOST_JS)
    with open(HOST_JS, 'r') as file:
        data = file.read()
    return ("200 OK", [("Content-Type","text/javascript")], data)

@web_app.route("/")
def main_page(request):
    print("Main page request received of type: ", request.method)
    print("Attempting to assemble website from: ", HOST_HTML)
    with open(HOST_HTML, 'r') as file:
        data = file.read()
    return ("200 OK", [("Content-Type","text/html; charset=utf-8")], data)

# Here we setup our server, passing in our web_app as the application
server.set_interface(esp)
wsgiServer = server.WSGIServer(80, application=web_app)

print("Starting Webserver!")
pinSet = False
wsgiServer.start()
loadFilenames()
updateHTML()
updateQueueData()
while True:
    # main loop, where the server polls for requests
    try:
        wsgiServer.update_poll()

        if uploadQueueChanged:
            print("Getting upload...")
            getUpload()
        if editQueueChanged:
            print("Editing queue...")
            handleEdit()

        if not pinSet and dev_pin.value:
            print("Dev pin disconnected!")
            pinSet = True
        elif not dev_pin.value and pinSet:
            print("Dev pin connected!")
            pinSet = False
    except (ValueError, RuntimeError, ConnectionError) as e:
        print("Failed to update server: ", e)
        continue