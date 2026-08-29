from pytubefix import YouTube
import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)
logger.setLevel(logging.WARNING)
logger.setLevel(logging.ERROR)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler = logging.FileHandler("logs/authClients.log")
handler.setFormatter(formatter)
logger.addHandler(handler)

class AuthClient:
    def __init__(self, url: str):
        self.url = url

        self.clients = [
            "WEB",
            "WEB_MUSIC",
            "ANDROID_MUSIC",
            "IOS_MUSIC",
            "WEB_SAFARI",
            "IOS",
            "ANDROID_VR",
            "TV",
        ]

        self.audio_streams = []
        self.progressive_streams = []
        self.type_stream = ""

    def __update_type(self, stream_type):
        self.type_stream = stream_type
        return self.type_stream

    def check_clients(self):
        logger.info("Checking available clients...")

        for client in self.clients:
            logger.info(f"Testing client: {client}")

            try:
                yt = YouTube(self.url, client)

                # Audio
                audio_streams = [
                    stream
                    for stream in yt.streams
                    if stream.mime_type.startswith("audio/")
                    and not stream.is_sabr
                ]

                if audio_streams:
                    self.audio_streams = audio_streams
                    self.__update_type("audio")

                    return (
                        self.audio_streams,
                        self.type_stream,
                        client,
                    )

                # Progressive
                progressive_streams = [
                    stream
                    for stream in yt.streams
                    if stream.is_progressive
                    and stream.mime_type.startswith("video/")
                    and not stream.is_sabr
                ]

                if progressive_streams:
                    self.progressive_streams = progressive_streams
                    self.__update_type("progressive")

                    return (
                        self.progressive_streams,
                        self.type_stream,
                        client,
                    )
                logger.error(f"  [ERROR] {client}: {type(e).__name__}: {e}")

            except Exception as e:
                logger.error(f"  [ERROR] {client}: {type(e).__name__}: {e}")
                continue

        return None