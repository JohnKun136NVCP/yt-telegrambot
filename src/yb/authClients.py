from pytubefix import YouTube
import logging

logger = logging.getLogger(__name__)

if not logger.handlers:
    logger.setLevel(logging.INFO)

    handler = logging.FileHandler("logs/authClients.log")
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


class AuthClient:

    def __init__(self, url: str):
        self.url = url

        self.clients = [
            "ANDROID_VR",
            "WEB",
            "WEB_MUSIC",
            "IOS_MUSIC",
            "IOS",
            "WEB_SAFARI",
            "ANDROID",
            "TV",
        ]

    def check_clients(self):

        logger.info("Checking available clients...")

        for client in self.clients:

            logger.info("Testing client: %s", client)

            try:

                yt = YouTube(
                    self.url,
                    client=client
                )

                streams = yt.streams

                audio_streams = [
                    stream
                    for stream in streams
                    if (
                        stream.mime_type
                        and stream.mime_type.startswith("audio/")
                        and not stream.is_sabr
                    )
                ]

                if audio_streams:

                    # Preferimos audio con mayor bitrate.
                    audio_streams.sort(
                        key=lambda s: (
                            s.abr or "0"
                        ),
                        reverse=True
                    )

                    audio = audio_streams[0]

                    logger.info(
                        "Client %s works: %s (%s)",
                        client,
                        audio,
                        audio.abr
                    )

                    return yt, audio, client

                logger.warning(
                    "Client %s has no compatible audio stream",
                    client
                )

            except Exception as e:

                logger.error(
                    "Client %s failed: %s: %s",
                    client,
                    type(e).__name__,
                    e
                )

        return None
