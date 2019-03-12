import requests
from urllib.parse import urlencode
from random import randint
from common.akatsuki.discord_hooks import Webhook
from objects import glob

class schiavo:
	"""
	Schiavo Bot class
	"""
	def __init__(self, botURL=None, prefix="", maxRetries=20):
		"""
		Initialize a new schiavo bot instance

		:param botURL: schiavo api url. oepsie i changed this a lot.
		:param maxRetries: max retries if api request fail. 0 = don't retry.
		"""
		self.maxRetries = 20

	def sendMessage(self, message, botURL):
		"""
		Send a generic message through schiavo api

		:param channel: api channel.
		:param message: message content.
		:param customParams: Let all hell break loose
		:return:

		Let's call it 50% spaghetti code.. Deal..?
		"""

		if botURL is None:
			return
		else:
			embed = Webhook(botURL, color=randint(100000, 999999))
			#embed.set_author(name='Aika', icon='https://a.vipsu.pw/999', url="http://vipsu.pw/")
			#embed.set_image('https://i.namir.in//bTr.png')
			#embed.set_title(title="Aika")
			embed.add_field(name=message, value='** **')

		for _ in range(0, self.maxRetries):
			try:
				embed.post()
				break
			except requests.RequestException:
				continue


	def sendConfidential(self, message):
		"""
		Send a message to #bunk

		:param message: message content.
		:return:
		"""
		botURL = glob.conf.config['webhooks']['confidential']
		self.sendMessage(message, botURL)

	def sendStaff(self, message):
		"""
		Send a message to #staff

		:param message: message content.
		:return:
		"""
		botURL = glob.conf.config['webhooks']['staff']
		self.sendMessage(message, botURL)

	def sendGeneral(self, message):
		"""
		Send a message to #general

		:param message: message content.
		:return:
		"""
		botURL = glob.conf.config['webhooks']['general']
		self.sendMessage(message, botURL)

	def sendChatlog(self, message):
		"""
		Send a message to #chatlog.

		:param message: message content.
		:return:
		"""
		botURL = glob.conf.config['webhooks']['chatlog']
		self.sendMessage(message, botURL)

	def sendCM(self, message):
		"""
		Send a message to #communitymanagers

		:param message: message content.
		:return:
		"""
		botURL = glob.conf.config['webhooks']['cm']
		self.sendMessage(message, botURL)
