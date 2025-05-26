import requests
import ssl
import time
ssl._create_default_https_context = ssl._create_unverified_context
class messagesAndQuotes:
    """
    A class to handle user messages and fetch random quotes from the ZenQuotes API.
    Attributes:
        url (str): The API endpoint for fetching random quotes.
        userMessage (str): Path to the file containing user messages.
        messageQuote (str): The text of the fetched quote.
        quouteString (str): The formatted quote string with author.
        authorQuote (str): The author of the fetched quote.
        quote (dict): The raw quote data fetched from the API.
        
    Methods:

        showMessageUser():
            Reads and returns the contents of the user message file.
            Returns an empty string if the file is not found.
        get_quote():
            Fetches a random quote from the ZenQuotes API.
            Returns the formatted quote string, or None if an error occurs.
    """

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
            time.sleep(2)  # Wait 2 seconds between requests
            response = requests.get(self.url, timeout=5)
            response.raise_for_status()
            data = response.json()
            self.quote = data[0]
            self.messageQuote = self.quote['q']
            self.authorQuote = self.quote['a']
            self.quouteString = f"{self.messageQuote} - {self.authorQuote}"
            return self.quouteString
        except requests.exceptions.RequestException as e:
            print(f"Error fetching quote: {e}")
            return None