from common.constants import bcolors
from common import generalUtils
from objects import glob
from common.ripple import userUtils
import time
import sys
import os

ENDL = "\n" if os.name == "posix" else "\r\n"

def logMessage(message, alertType = "INFO", messageColor = bcolors.ENDC, discord = None, of = None, stdout = True):
	"""
	Log a message

	:param message: message to log
	:param alertType: alert type string. Can be INFO, WARNING, ERROR or DEBUG. Default: INFO
	:param messageColor: message console ANSI color. Default: no color
	:param discord: Discord channel acronym for Schiavo. If None, don't log to Discord. Default: None
	:param of:	Output file name (inside .data folder). If None, don't log to file. Default: None
	:param stdout: If True, log to stdout (print). Default: True
	:return:
	"""
	# Get type color from alertType
	if alertType == "INFO":
		typeColor = bcolors.CYAN
	elif alertType == "WARNING":
		typeColor = bcolors.YELLOW
	elif alertType == "ERROR":
		typeColor = bcolors.RED
	elif alertType == "CHAT":
		typeColor = bcolors.BLUE
	elif alertType == "DEBUG":
		typeColor = bcolors.PINK
	elif alertType == "CMYUI":
		typeColor = bcolors.PINK
	else:
		typeColor = bcolors.ENDC

	# Message without colors
	finalMessage = "[{time}] {type} - {message}".format(time=generalUtils.getTimestamp(), type=alertType, message=message)

	# Message with colors
	finalMessageConsole = "{typeColor}[{time}] {type}{endc} - {messageColor}{message}{endc}".format(
		time=generalUtils.getTimestamp(),
		type=alertType,
		message=message,
		typeColor=typeColor,
		messageColor=messageColor,
		endc=bcolors.ENDC)

	# Log to console
	if stdout:
		print(finalMessageConsole)
		sys.stdout.flush()

	# Log to discord if needed
	if discord is not None:
		if discord == "bunker":
			glob.schiavo.sendConfidential(message)
		elif discord == "cm":
			glob.schiavo.sendCM(message)
		elif discord == "staff":
			glob.schiavo.sendStaff(message)
		elif discord == "general":
			glob.schiavo.sendGeneral(message)

	# Log to file if needed
	if of is not None:
		glob.fileBuffers.write(".data/"+of, finalMessage+ENDL)

def warning(message, discord = None):
	"""
	Log a warning to stdout and optionally to Discord

	:param message: warning message
	:param discord: Discord channel acronym for Schiavo. If None, don't log to Discord. Default: None
	:return:
	"""
	logMessage(message, "WARNING", bcolors.YELLOW, discord)

def error(message, discord = None):
	"""
	Log a warning message to stdout and optionally to Discord

	:param message: warning message
	:param discord: Discord channel acronym for Schiavo. If None, don't log to Discord. Default: None
	:return:
	"""
	logMessage(message, "ERROR", bcolors.RED, discord)

def info(message, discord = None):
	"""
	Log an info message to stdout and optionally to Discord

	:param message: info message
	:param discord: Discord channel acronym for Schiavo. If None, don't log to Discord. Default: None
	:return:
	"""
	logMessage(message, "INFO", bcolors.ENDC, discord)

def debug(message):
	"""
	Log a debug message to stdout.
	Works only if the server is running in debug mode.

	:param message: debug message
	:return:
	"""
	if glob.debug:
		logMessage(message, "DEBUG", bcolors.PINK)

def chat(message):
	"""
	Log a public chat message to stdout and to chatlog_public.txt.

	:param message: message content
	:return:
	"""
	logMessage(message, "CHAT", bcolors.BLUE, of="chatlog_public.txt")

def pm(message):
	"""
	Log a private chat message to stdout and to chatlog_private.txt.

	:param message: message content
	:return:
	"""
	logMessage(message, "CMYUI", bcolors.CYAN, of="chatlog_private.txt")

def hoshio(message, discord=None):
	"""
	Just a log that is meant to stand out in console. Meant for testing things, generally..

	:param message: message content
	:return:
	"""
	logMessage(message, "HOSHIO", bcolors.CYAN, discord)

def rap(userID, message, discord=False, through="Charlotte"):
	"""
	Log a message to Admin Logs.

	:param userID: admin user ID
	:param message: message content, without username
	:param discord: if True, send the message to discord
	:param through: through string. Default: FokaBot
	:return:
	"""
	glob.db.execute("INSERT INTO rap_logs (id, userid, text, datetime, through) VALUES (NULL, %s, %s, %s, %s)", [userID, message, int(time.time()), through])
	username = userUtils.getUsername(userID)
	logMessage("{} {}".format(username, message), discord=True)
