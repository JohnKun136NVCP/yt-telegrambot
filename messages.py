"""
This module provides functionality for managing user messages and fetching random quotes
from an external API.
Classes:
    messagesAndQuotes: A class to handle user messages and fetch random quotes.
Methods:
    __init__():
        Initializes the messagesAndQuotes class with default attributes.
    showMessageUser():
        Reads and returns the content of a user message file. If the file is not found,
        it prints an error message and returns an empty string.
    get_quote():
        Fetches a random quote from the ZenQuotes API, processes the response, and
        returns the quote as a formatted string. If an error occurs during the API
        request, it prints an error message.

"""

import requests
import ssl
ssl._create_default_https_context = ssl._create_unverified_context
class messagesAndQuotes:
    def __init__(self):
        self.url = "https://zenquotes.io?api=random"
        self.userMessage = "Messages/MessageUser.md"
        self.messageQuote = str
        self.quouteString = str
        self.authorQuote = str
        self.quote = dict

    def showMessageUser(self):
        try:
            with open(self.userMessage,"r") as file:
                lines = file.read().strip()
                return lines
        except FileNotFoundError:
            print(f"File {self.userMessage} not found.")
            return ""

    def get_quote(self):
        try:
            response = requests.get(self.url,timeout=5)
            response.raise_for_status()
            data = response.json()
            self.quote = data[0]
            self.messageQuote = self.quote['q']
            self.authorQuote = self.quote['a']
            self.quouteString = f"{self.messageQuote} - {self.authorQuote}"
            if self.quote:
                return self.quouteString
        except requests.exceptions.RequestException as e:
            print(f"Error fetching quote: {e}")
        