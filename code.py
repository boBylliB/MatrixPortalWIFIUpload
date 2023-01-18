# SPDX-FileCopyrightText: 2022 boBylliB
# SPDX-License-Identifier: MIT

# Initial code (for testing and setup, thank you Adafruit) referenced from:
# SPDX-FileCopyrightText: 2019 ladyada for Adafruit Industries
# SPDX-License-Identifier: MIT

import traceback
import board
import gc
import math
import time
import busio
import os
import displayio
import framebufferio
import rgbmatrix
import adafruit_display_text.label as label
from adafruit_bitmap_font import bitmap_font
import adafruit_imageload
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

print("Matrix Portal Webserver-Controlled Display")

TEXT_URL = "http://wifitest.adafruit.com/testwifi/index.html"
HOST_HTML = "web/index.html"
HOST_JS = "web/scripts/main.js"
FILENAMES = "filenames.txt"

MAXSIZE = 4096

BITMAP_FONTS = "bitmapfonts/"
FIRST_ASCII_VALUE = ord('!')
SPACE_INDEX = 32 * 3 - 1

VERSION_FILE = "version.txt"
VERSION_PREFIX = "<a class=\"Link--primary\" href=\"/boBylliB/MatrixPortalWIFIUpload/releases"
GITHUB_URL = "https://api.github.com/repos/boBylliB/MatrixPortalWIFIUpload/releases"

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

#Initializing WIFI functionality
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
print("\nMy IP address is", esp.pretty_ip(esp.ip_address), "\n")
print("Ping google.com: %d ms" % esp.ping("google.com"))

# esp._debug = True
print("Fetching text from", TEXT_URL)
r = requests.get(TEXT_URL)
print("-" * 40)
print(r.text)
print("-" * 40)
r.close()

def getTime():
    return time.monotonic_ns() / 1000000000

# Initializing display
displayio.release_displays()
matrix = rgbmatrix.RGBMatrix(
    width=64, bit_depth=4,
    rgb_pins=[
        board.MTX_R1,
        board.MTX_G1,
        board.MTX_B1,
        board.MTX_R2,
        board.MTX_G2,
        board.MTX_B2
    ],
    addr_pins=[
        board.MTX_ADDRA,
        board.MTX_ADDRB,
        board.MTX_ADDRC,
        board.MTX_ADDRD
    ],
    clock_pin=board.MTX_CLK,
    latch_pin=board.MTX_LAT,
    output_enable_pin=board.MTX_OE
)
display = framebufferio.FramebufferDisplay(matrix, auto_refresh=False)

# Relevant datastructures
filenames = []
fileInfo = []
queueData = ""
editQueue = []
editQueueChanged = False
uploadQueue = []
uploadQueueChanged = False

displayGroup = displayio.Group()
display.show(displayGroup)

currentDisplayItem = {}
currentDisplayItem['type'] = "blank"
currentDisplayItem['prevTime'] = getTime()

# Helper functions for display

def getFontBitmap(height):
    if height < 5 or height > 32:
        errortext = "Requested font height " + str(height) + " doesn't exist."
        errortext += "Please use font height 5, 10, 15, 20, 25, or 30"
        raise ValueError(errortext)
    
    with open(BITMAP_FONTS + str(height) + ".txt") as settingfile:
        settings = settingfile.readlines()

    width = -1
    for setting in settings:
        name, value = setting.split('=')
        if name == "width":
            width = int(value)
    if width == -1:
        raise ValueError("Width not found in the font settings!")

    filename = BITMAP_FONTS + str(height) + ".bmp"
    bitmap, palette = adafruit_imageload.load(filename, bitmap=displayio.Bitmap, palette=displayio.Palette)

    return [bitmap, palette, width]

def displayText(messages, height, scrollDelay, scrollSpeed, wordWrap, color):
    global currentDisplayItem
    global displayGroup

    bitmap, palette, width = getFontBitmap(height)
    palette[0] = color
    lines = [displayio.Group() for _ in range(len(messages))]
    lineLengths = [0 for _ in range(len(lines))]
    
    currentDisplayItem['type'] = "text"
    currentDisplayItem['scrollSpeed'] = scrollSpeed
    currentDisplayItem['scrollDelay'] = scrollDelay

    if wordWrap:
        currentDisplayItem['isVertical'] = True
        willScroll = False
        for idx in range(len(lines)):
            message = messages[idx]
            words = []
            word = ""
            newlineDetected = False
            for char in message:
                if char == ' ':
                    words.append(word)
                    word = ""
                elif char == '\n':
                    newlineDetected = True
                    words.append(word)
                    word = ""
                else:
                    if newlineDetected:
                        word += '\n'
                        newlineDetected = False
                    word += char
            if not word == "":
                words.append(word)
            maxWidth = math.floor(64 / width) - 1
            tilegridLine = [SPACE_INDEX for _ in range(maxWidth + 1)]
            tilegridMatrix = []
            posX = 0
            posY = 0
            for wordIdx in range(len(words)):
                word = words[wordIdx]
                wordLength = len(word)
                if (posX + wordLength) > maxWidth and wordIdx > 0:
                    tilegridMatrix.append(tilegridLine)
                    tilegridLine = [SPACE_INDEX for _ in range(maxWidth + 1)]
                    posX = 0
                    posY += 1

                for charIdx in range(len(word)):
                    if posX > maxWidth:
                        tilegridMatrix.append(tilegridLine)
                        tilegridLine = [SPACE_INDEX for _ in range(maxWidth + 1)]
                        posX = 0
                        posY += 1

                    sourceIdx = ord(word[charIdx]) - FIRST_ASCII_VALUE
                    if sourceIdx < 0:
                        sourceIdx = SPACE_INDEX

                    if word[charIdx] == '\n':
                        tilegridMatrix.append(tilegridLine)
                        tilegridLine = [SPACE_INDEX for _ in range(maxWidth + 1)]
                        posX = 0
                        posY += 1
                    else:
                        tilegridLine[posX] = sourceIdx
                        posX += 1

                if posX < maxWidth:
                    posX += 1

                if posX == maxWidth and wordIdx < len(words) - 1:
                    tilegridMatrix.append(tilegridLine)
                    tilegridLine = [SPACE_INDEX for _ in range(maxWidth + 1)]
                    posX = 0
                    posY += 1

            if posX > 0:
                tilegridMatrix.append(tilegridLine)

            numSubLines = len(tilegridMatrix)

            tilegrid = displayio.TileGrid(bitmap=bitmap, pixel_shader=palette, width=(maxWidth + 1), height=numSubLines, tile_width=width, tile_height=height, default_tile=SPACE_INDEX)
            for yIdx in range(numSubLines):
                for xIdx in range(maxWidth + 1):
                    tilegrid[xIdx, yIdx] = tilegridMatrix[yIdx][xIdx]

            lines[idx].append(tilegrid)
            lineLengths[idx] = numSubLines * height
            if numSubLines * height > 32:
                willScroll = True

            lines[idx].x = 0
            if scrollDelay > 0:
                lines[idx].y = 0
            else:
                lines[idx].y = 32

        displayGroup.append(lines[0])
        currentDisplayItem['currentLine'] = 0
        currentDisplayItem['scrolling'] = False
        currentDisplayItem['willScroll'] = willScroll
    else:
        currentDisplayItem['isVertical'] = False
        willScroll = False
        for idx in range(len(lines)):
            lines[idx].y = math.floor((32 / 2) - (height / 2))
            if scrollDelay > 0:
                lines[idx].x = 0
            else:
                lines[idx].x = 64
            message = messages[idx]
            tilegridList = []
            for char in message:
                sourceIdx = ord(char) - FIRST_ASCII_VALUE
                if sourceIdx < 0:
                    sourceIdx = SPACE_INDEX

                if char == '\n':
                    for _ in range(math.floor(64 / width)):
                        tilegridList.append(SPACE_INDEX)
                else:
                    tilegridList.append(sourceIdx)
            tilegrid = displayio.TileGrid(bitmap=bitmap, pixel_shader=palette, width=len(tilegridList), height=1, tile_width=width, tile_height=height, default_tile=SPACE_INDEX)
            for tileIdx in range(len(tilegridList)):
                tilegrid[tileIdx] = tilegridList[tileIdx]
            lines[idx].append(tilegrid)
            lineLengths[idx] = len(tilegridList) * width
            if len(tilegridList) * width > 64:
                willScroll = True
            
        displayGroup.append(lines[0])
        currentDisplayItem['currentLine'] = 0
        currentDisplayItem['scrolling'] = False
        currentDisplayItem['willScroll'] = willScroll

    currentDisplayItem['lines'] = lines
    currentDisplayItem['lineLengths'] = lineLengths
    currentDisplayItem['prevTime'] = getTime()

def displayTextfile(filename):
    extension = filename.split('.')[1]
    if extension == "msg":
        with open(filename, 'r') as file:
            height = int(file.readline().split('=')[1])
            scrollDelay = int(file.readline().split('=')[1])
            scrollSpeed = int(file.readline().split('=')[1])
            wordWrapChoice = file.readline().split('=')[1]
            if wordWrapChoice == "on":
                wordWrap = True
            else:
                wordWrap = False
            colorChoice = str(file.readline().split('=')[1])
            color = int('0x' + colorChoice)

            messages = file.readlines()
    else:
        height = 30
        scrollDelay = 0
        scrollSpeed = 30
        wordWrap = False
        color = 0xFFFFFF

        with open(filename, 'r') as file:
            messages = file.readlines()

    lastMessage = messages[len(messages) - 1]
    if len(lastMessage) < 2:
        messages = messages[:-1]

    displayText(messages, height, scrollDelay, scrollSpeed, wordWrap, color)

def displayAnimation(bitmap, palette, framesPerSecond):
    global currentDisplayItem
    global displayGroup
    currentDisplayItem['type'] = "animation"
    currentDisplayItem['frameDelay'] = 1 / framesPerSecond
    numFrames = bitmap.height / 32
    tilegrid = displayio.TileGrid(bitmap, pixel_shader=palette, height=numFrames, tile_width=64, tile_height=32)
    for tileIdx in range(numFrames):
        tilegrid[tileIdx] = tileIdx
    displayGroup.append(tilegrid)
    currentDisplayItem['tilegrid'] = tilegrid
    currentDisplayItem['currentFrame'] = 0
    currentDisplayItem['numFrames'] = numFrames
    currentDisplayItem['prevTime'] = getTime()

def displayImagefile(filename):
    extension = filename.split('.')[1]
    if extension == "bmp":
        bitmap, palette = adafruit_imageload.load(filename, bitmap=displayio.Bitmap, palette=displayio.Palette)
        animTag = filename.find('ANIM')
        if animTag > -1:
            framerate = filename[(animTag+4):(animTag+6)]
            if framerate.isnumeric():
                framesPerSecond = int(framerate)
            else:
                framesPerSecond = 20
            displayAnimation(bitmap, palette, framesPerSecond)
        else:
            try:
                metafilename = filename.split('.')[0].split('/')[1] + '.txt'
                with open('metadata/' + metafilename, 'r') as file:
                    settings = file.readlines()

                    displayTime = 5
                    for setting in settings:
                        name, value = setting.split('=')
                        if name == "displaytime":
                            displayTime = int(value)
            except (OSError, ValueError) as e:
                print("Unable to open the metadata file for", filename, "due to", e)
                displayTime = 5
            displayImage(bitmap, palette, displayTime)

def displayImage(bitmap, palette, displayTime):
    global currentDisplayItem
    global displayGroup
    currentDisplayItem['type'] = "image"
    currentDisplayItem['displayTime'] = displayTime
    tilegrid = displayio.TileGrid(bitmap, pixel_shader=palette)
    if bitmap.width < 64:
        tilegrid.x = math.floor((64 - bitmap.width) / 2)
    if bitmap.height < 32:
        tilegrid.y = math.floor((32 - bitmap.width) / 2)
    displayGroup.append(tilegrid)
    currentDisplayItem['prevTime'] = getTime()

def displayFile(filename):
    extension = filename.split('.')[1]
    if extension == "txt" or extension == "msg":
        displayTextfile(filename)
    elif extension == "bmp":
        displayImagefile(filename)
    else:
        print("File", filename, "has an unrecognized filetype of", extension)

def updateDisplayItem():
    global currentDisplayItem
    global displayGroup
    currentTime = getTime()
    if currentDisplayItem['type'] == "text":
        if not currentDisplayItem['scrolling']:
            if currentTime - currentDisplayItem['prevTime'] < currentDisplayItem['scrollDelay']:
                return
            elif currentDisplayItem['willScroll']:
                currentDisplayItem['scrolling'] = True
                currentDisplayItem['prevTime'] = getTime()
            else:
                displayGroup.pop()
                currentDisplayItem['prevTime'] = getTime()
                currentDisplayItem['currentLine'] += 1
                if currentDisplayItem['currentLine'] >= len(currentDisplayItem['lines']):
                    currentDisplayItem['type'] = "blank"
                else:
                    displayGroup.append(currentDisplayItem['lines'][currentDisplayItem['currentLine']])
                    currentDisplayItem['prevTime'] = getTime()
        else:
            if currentDisplayItem['isVertical']:
                if currentDisplayItem['lines'][currentDisplayItem['currentLine']].y < -currentDisplayItem['lineLengths'][currentDisplayItem['currentLine']]:
                    currentDisplayItem['scrolling'] = False
                    displayGroup.pop()
                    currentDisplayItem['prevTime'] = getTime()
                    currentDisplayItem['currentLine'] += 1
                    if currentDisplayItem['currentLine'] >= len(currentDisplayItem['lines']):
                        currentDisplayItem['type'] = "blank"
                    else:
                        displayGroup.append(currentDisplayItem['lines'][currentDisplayItem['currentLine']])
                        currentDisplayItem['prevTime'] = getTime()
                else:
                    elapsedTime = currentTime - currentDisplayItem['prevTime']
                    scrollDistance = math.floor(currentDisplayItem['scrollSpeed'] * elapsedTime)
                    if scrollDistance > 0:
                        currentDisplayItem['lines'][currentDisplayItem['currentLine']].y -= scrollDistance
                        currentDisplayItem['prevTime'] = getTime()
            else:
                if -currentDisplayItem['lines'][currentDisplayItem['currentLine']].x > currentDisplayItem['lineLengths'][currentDisplayItem['currentLine']]:
                    currentDisplayItem['scrolling'] = False
                    displayGroup.pop()
                    currentDisplayItem['prevTime'] = getTime()
                    currentDisplayItem['currentLine'] += 1
                    if currentDisplayItem['currentLine'] >= len(currentDisplayItem['lines']):
                        currentDisplayItem['type'] = "blank"
                    else:
                        displayGroup.append(currentDisplayItem['lines'][currentDisplayItem['currentLine']])
                        currentDisplayItem['prevTime'] = getTime()
                else:
                    elapsedTime = currentTime - currentDisplayItem['prevTime']
                    scrollDistance = math.floor(currentDisplayItem['scrollSpeed'] * elapsedTime)
                    if scrollDistance > 0:
                        currentDisplayItem['lines'][currentDisplayItem['currentLine']].x -= scrollDistance
                        currentDisplayItem['prevTime'] = getTime()
    elif currentDisplayItem['type'] == "image":
        elapsedTime = currentTime - currentDisplayItem['prevTime']
        if elapsedTime > currentDisplayItem['displayTime']:
            displayGroup.pop()
            currentDisplayItem['type'] = "blank"
            currentDisplayItem['prevTime'] = getTime()
    elif currentDisplayItem['type'] == "animation":
        elapsedTime = currentTime - currentDisplayItem['prevTime']
        if elapsedTime > currentDisplayItem['frameDelay']:
            if currentDisplayItem['currentFrame'] < (currentDisplayItem['numFrames'] - 1):
                currentDisplayItem['currentFrame'] += 1
                currentDisplayItem['tilegrid'].y = currentDisplayItem['currentFrame'] * 32
            else:
                displayGroup.pop()
                currentDisplayItem['type'] == "blank"
            currentDisplayItem['prevTime'] = getTime()
    else:
        if len(filenames) > 0:
            displayFile('uploads/' + filenames[0])
            rotateFilenames()

# Helper functions for webserver

def rotateFilenames():
    filenames.append(filenames[0])
    filenames.pop(0)

def validIdx(idx, array):
    return (idx >= 0 and idx < len(array))

def removeFilename(targetIdx):
    if validIdx(targetIdx, filenames):
        os.remove("uploads/" + filenames[targetIdx])
        try:
            metafilename = filenames[targetIdx].strip('.')[0] + '.txt'
            os.remove("metadata/" + metafilename)
        except OSError as e:
            print("No metadata deleted for", filenames[targetIdx])
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

def singleDownload(upload.body, filename, filesize, boundary, isMetadata):
    print('Small file detected, downloading directly')
    if isMetadata:
        try:
            with open('metadata/' + filename, 'w') as file:
                file.write(upload.body.read(filesize))
        except UnicodeDecodeError as e:
            print("UnicodeDecodeError: ", e)
            print("Attempting to write to file in binary...")
            with open('metadata/' + filename, 'wb') as file:
                file.write(bytes(upload.body.read(filesize)))
    else:
        try:
            with open('uploads/' + filename, 'w') as file:
                file.write(upload.body.read(filesize))
        except UnicodeDecodeError as e:
            print("UnicodeDecodeError: ", e)
            print("Attempting to write to file in binary...")
            with open('uploads/' + filename, 'wb') as file:
                file.write(bytes(upload.body.read(filesize)))
        filenames.append(filename)

    if hasMetadata:
        try:
            with open('uploads/' + metafile, 'r') as oldFile:
                filedata = oldFile.read()
            with open('metadata/' + metafile, 'w') as newFile:
                newFile.write(filedata)
        except UnicodeDecodeError as e:
            print("UnicodeDecodeError: ", e)
            print("Attempting to write to file in binary...")
            with open('uploads/' + metafile, 'rb') as oldFile:
                filedata = bytes(oldFile.read())
            with open('metadata/' + metafile, 'wb') as newFile:
                newFile.write(filedata)

def streamDownload(upload.body, filename, filesize, boundary, isMetadata):
    print('Large file detected, streaming')
    bytesRead = 0
    while bytesRead < filesize:
        print("Bytes read so far:", bytesRead)
        if filesize - bytesRead > MAXSIZE:
            chunk = upload.body.read(chunk)
        else:
            chunk = filesize - bytesRead
        print("Chunk size:", chunk)

        if bytesRead == 0:
            if isMetadata:
                with open('metadata/' + filename, 'wb') as file:
                    file.write(bytes(upload.body.read(chunk)))
            else:
                with open('uploads/' + filename, 'wb') as file:
                    file.write(bytes(upload.body.read(chunk)))
        else:
            if isMetadata:
                with open('metadata/' + filename, 'ab') as file:
                    file.write(bytes(upload.body.read(chunk)))
            else:
                with open('uploads/' + filename, 'ab') as file:
                    file.write(bytes(upload.body.read(chunk)))

        bytesRead += chunk

    if not isMetadata:
        filenames.append(filename)

def getUpload():
    global uploadQueueChanged

    if len(uploadQueue) < 1:
        return

    for idx in range(len(uploadQueue)):
        upload = uploadQueue[idx]

        print(upload.body.read())
        upload.body.seek(0)

        boundary = upload.body.readline().strip()
        filename = upload.body.readline().split('filename=')[1].split('"')[1]
        print("Filename: ", filename)
        upload.body.readline()
        upload.body.readline()

        boundarySize = len("\n--" + boundary)

        currentPos = upload.body.tell()
        upload.body.seek(0, 2)
        endPos = upload.body.tell()
        upload.body.seek(currentPos)
        filesize = endPos - currentPos - boundarySize
        print("Filesize: ", filesize)

        isMetadata = False
        hasMetadata = False
        metafile = ""
        for jdx in range(len(filenames)):
            if filenames[jdx] == filename:
                print("Duplicate found, removing from list.")
                filenames.pop(jdx)
            elif filenames[jdx].split('.')[0] == filename.split('.')[0]:
                print("Newly uploaded file has duplicate name but different extension.")
                if filename.split('.')[1] == 'txt':
                    print("Treating newly uploaded file as metadata.")
                    isMetadata = True
                elif filenames[jdx].split('.')[1] == 'txt':
                    print("Treating previous file as metadata.")
                    hasMetadata = True
                    metafile = filenames[jdx]

        if filesize < MAXSIZE:
            singleDownload(upload.body, filename, filesize, boundary, isMetadata, hasMetadata)
        else:
            streamDownload(upload.body, filename, filesize, boundary, isMetadata, hasMetadata)

        if hasMetadata:
            os.rename(('uploads/' + filename), ('metadata/' + filename))

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

        if targetIdx == -1 and not action == "Clear+Queue":
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

@web_app.route("/softwareUpdate")
def checkForSoftwareUpdate(request):
    print("Software update request received of type: ", request.method)
    websiteData = requests.get(GITHUB_URL).json()[0]['name']
    print("Github returned: ", websiteData)
    currentVersion = ""
    with open(VERSION_FILE, 'r') as file:
        currentVersion = file.read().strip()
    newestVersion = websiteData.split(':',1)[0].strip()
    print("Current:", currentVersion, "; Newest:", newestVersion)
    data = "<p>"
    if newestVersion == currentVersion:
        data += "Software is up to date!"
    else:
        data += "Software update available!"
    data +="</p>"
    return ("200 OK", [("Content-Type","text/plain")], data)

@web_app.route("/queueUpdate")
def updateQueue(request):
    global queueData
    print("Queue update request received of type: ", request.method)
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

ipmessage = ["Website hosted at: " + esp.pretty_ip(esp.ip_address)]
displayText(ipmessage, 5, 20, 5, True, 0xffffff)

print("Starting Webserver!")
pinSet = False
wsgiServer.start()
loadFilenames()
updateHTML()
updateQueueData()
while True:
    # main loop, where the server polls for requests
    try:
        gc.collect()
        updateDisplayItem()
        display.refresh(minimum_frames_per_second=0)

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
        
        wsgiServer.update_poll()
    except (ValueError, RuntimeError, ConnectionError) as e:
        print("Failed to update server: ", e)
        traceback.print_exception(e,e,e.__traceback__)
        continue