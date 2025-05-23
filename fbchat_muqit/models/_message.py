from __future__ import annotations

from dataclasses import field, dataclass
import json
from string import Formatter
from typing import Any, List, Dict, Optional, Union
from ._thread import ThreadType, ThreadLocation
from . import _attachment, _location, _file, _sticker
from .. import _util
from ._quick_reply import QuickReplyText, QuickReplyEmail, QuickReplyLocation, QuickReplyPhoneNumber, graphql_to_quick_reply
from ._core import CustomEnum

QuickReplies = Union[
    QuickReplyPhoneNumber,
    QuickReplyLocation,
    QuickReplyEmail,
    QuickReplyText
]


class EmojiSize(CustomEnum):
    """
    Specifies the size of an emoji sent in a message.

    Attributes:
        LARGE: Represents a large emoji.
        MEDIUM: Represents a medium emoji.
        SMALL: Represents a small emoji.
    """

    LARGE = "369239383222810"
    MEDIUM = "369239343222814"
    SMALL = "369239263222822"

    @classmethod
    def _from_tags(cls, tags: List[str])-> Optional[EmojiSize]:

        string_to_emojisize: Dict = {
            "large": cls.LARGE,
            "medium": cls.MEDIUM,
            "small": cls.SMALL,
            "l": cls.LARGE,
            "m": cls.MEDIUM,
            "s": cls.SMALL,
        }
        for tag in tags or ():
            data = tag.split(":", 1)
            if len(data) > 1 and data[0] == "hot_emoji_size": 
                return string_to_emojisize[data[1]]
                
        return None


class MessageReaction(CustomEnum):
    """
    Specifies the type of reaction to a message.

    Attributes:
        HEART: Represents a heart reaction.
        LOVE: Represents a love reaction.
        SMILE: Represents a smile reaction.
        WOW: Represents a wow reaction.
        SAD: Represents a sad reaction.
        ANGRY: Represents an angry reaction.
        YES: Represents a thumbs-up reaction.
        NO: Represents a thumbs-down reaction.
    """

    HEART = "❤"
    LOVE = "😍"
    SMILE = "😆"
    WOW = "😮"
    SAD = "😢"
    ANGRY = "😠"
    YES = "👍"
    NO = "👎"


@dataclass(eq=False)
class Mention:
    """
    Represents a mention in a message.

    Attributes:
        thread_id: The ID of the thread being mentioned.
        offset: The character offset where the mention starts.
        length: The length of the mention.
    """
    thread_id: str = field()
    offset: int = field(default=0)
    length: int = field(default=10)


@dataclass(eq=False)
class MessageFunc:
    """
    MessageFunc is the Base class for message-related actions such as reacting, replying, and unsending.

    """

    uid: str = field(init=False)
    """The unique identifier for the message."""

    client: Any = field(init=False)
    """client: Reference to the Client instance."""

    author: str = field(init=False)
    """ID of the message sender."""

    thread_id: str = field(init=False)
    """ID of the thread where the message belongs."""

    thread_type: Any = field(init=False)
    """Type of the thread (e.g., USER, GROUP)."""

    @property
    def state(self):
        return self.client._state



    async def react(self, reaction: str):
        """
        React to a message.

        Args:
            reaction: The reaction to apply, or None to remove the reaction.

        Raises:
            RuntimeError: If the reaction action fails.
        """
        data = {
        "action": "ADD_REACTION" if reaction else "REMOVE_REACTION",
        "client_mutation_id": "1",
        "actor_id": self.client.uid,
        "message_id": self.uid,
        "reaction": reaction,
        }
        data = {
            "doc_id": 1491398900900362,
            "variables": _util.json_minimal({"data": data}),
        }
        try:
            await self.state._payload_post("/webgraphql/mutation", data)
        except Exception as e:
            raise RuntimeError("failed reacting: ", e)


    async def reply(self, message):
        """
        Reply to a message.

        Args:
            message: The text of the reply.
        """
        data = {}
        if self.thread_type == ThreadType.USER:
            data = {
                "other_user_fbid": self.thread_id,
                "action_type": "ma-type:user-generated-message",
                "body": message,
                "replied_to_message_id": self.uid
            }

            await self.state.do_send_request(data)

        elif self.thread_type == ThreadType.GROUP:
            data = {
                "thread_fbid": self.thread_id,
                "action_type": "ma-type:user-generated-message",
                "body": message,
                "replied_to_message_id": self.uid
                }
            await self.state.do_send_request(data)


    async def unsend(self):
        """
        Unsend (delete) the message if the author is the current user.

        Prints:
            Success message upon completion.
        """
        if self.author == self.state.user_id:
            data = {"message_id": self.uid}
            await self.state._payload_post("/messaging/unsend_message/?dpr=1", data)
            print("message deleted succesfully")


@dataclass(eq=False)
class Message(MessageFunc):
    """
    Message class Represents a Facebook message with its details.
    """

    text: Optional[str] = field(default=None)
    """The text of the message"""

    mentions: List[Mention] = field(default_factory=list)
    """A list of Mention object"""

    emoji_size: Optional[EmojiSize] = field(default=None)
    """The size of a sent emoji"""

    uid: str = field(init=False)
    """The ID of the message"""

    author: str = field(init=False)
    """The ID of the message sender"""

    timestamp: Optional[int] = field(default=None, init=False)
    """The timestamp when the message was sent"""

    is_read: Optional[bool] = field(default=None, init=False)
    """If the message was read by anyone or not"""

    read_by: List[str] = field(default_factory=list, init=False)
    """A list of people IDs who read the message, works only with :func:`~fbchat_muqit.Client.fetchThreadMessages`"""

    reactions: Dict[str, MessageReaction] = field(default_factory=dict, init=False)
    """A dictionary with user's IDs as keys, and their :class:`MessageReaction` as values"""

    sticker: Optional[_sticker.Sticker] = field(default=None)
    """A :class:`Sticker`"""

    attachments: List[_attachment.Attachment] = field(default_factory=list)
    """A List of Attachment obeject"""

    quick_replies: Optional[List[QuickReplies]] = field(default_factory=list)
    """A list of :class:`QuickReply`"""

    unsent: bool = field(default=False, init=False)
    """Whether the message is unsent (deleted for everyone)"""

    reply_to_id: Optional[str] = field(default=None)
    """The message ID you want to reply"""

    replied_to: Optional[Message] = field(default=None, init=False)
    """Message object if the current message is a reply message"""

    location: Optional[str] = field(default=None)
    """Thread location of the message INBOX, ARCHAIVE, SPAM etc."""
    
    forwarded: bool = field(default=False, init=False)
    """Whether The message was forwarded"""



    def __post_init__(self):
        # Converter logic for mentions
        if self.mentions is None:
            self.mentions = []
        if self.attachments is None:
            self.attachments = []
        if self.quick_replies is None:
            self.quick_replies = []
        if isinstance(self.emoji_size, str):
            self.emoji_size = EmojiSize(self.emoji_size)
    

    @classmethod
    def formatMentions(cls, text, *args, **kwargs):
        # """Like `str.format`, but takes tuples with a thread id and text instead.
        #
        # Return a `Message` object, with the formatted string and relevant mentions.
        #
        # >>> Message.formatMentions("Hey {!r}! My name is {}", ("1234", "Peter"), ("4321", "Michael"))
        # <Message (None): "Hey 'Peter'! My name is Michael", mentions=[<Mention 1234: offset=4 length=7>, <Mention 4321: offset=24 length=7>] emoji_size=None attachments=[]>
        #
        # >>> Message.formatMentions("Hey {p}! My name is {}", ("1234", "Michael"), p=("4321", "Peter"))
        # <Message (None): 'Hey Peter! My name is Michael', mentions=[<Mention 4321: offset=4 length=5>, <Mention 1234: offset=22 length=7>] emoji_size=None attachments=[]>
        # """
        result = ""
        mentions = list()
        offset = 0
        f = Formatter()
        field_names = [field_name[1] for field_name in f.parse(text)]
        automatic = "" in field_names
        i = 0

        for (literal_text, field_name, format_spec, conversion) in f.parse(text):
            offset += len(literal_text)
            result += literal_text

            if field_name is None:
                continue

            if field_name == "":
                field_name = str(i)
                i += 1
            elif automatic and field_name.isdigit():
                raise ValueError(
                    "cannot switch from automatic field numbering to manual field specification"
                )

            thread_id, name = f.get_field(field_name, args, kwargs)[0]

            if format_spec:
                name = f.format_field(name, format_spec)
            if conversion:
                name = f.convert_field(name, conversion)

            result += name
            mentions.append(
                Mention(thread_id=thread_id, offset=offset, length=len(name))
            )
            offset += len(name)

        message = cls(text=result, mentions=mentions)
        return message

    @staticmethod
    def _get_forwarded_from_tags(tags):
        if tags is None:
            return False
        return any(map(lambda tag: "forward" in tag or "copy" in tag, tags))

    def _to_send_data(self)-> Dict:
        data = {}

        if self.text or self.sticker or self.emoji_size:
            data["action_type"] = "ma-type:user-generated-message"

        if self.text:
            data["body"] = self.text

        for i, mention in enumerate(self.mentions):
            data["profile_xmd[{}][id]".format(i)] = mention.thread_id
            data["profile_xmd[{}][offset]".format(i)] = mention.offset
            data["profile_xmd[{}][length]".format(i)] = mention.length
            data["profile_xmd[{}][type]".format(i)] = "p"

        if self.emoji_size:
            if self.text:
                data["tags[0]"] = "hot_emoji_size:" + self.emoji_size.name.lower()
            else:
                data["sticker_id"] = self.emoji_size.value

        if self.sticker:
            data["sticker_id"] = self.sticker.uid

        if self.quick_replies:
            xmd = {"quick_replies": []}
            for quick_reply in self.quick_replies:
                # TODO: Move this to `_quick_reply.py`
                q = dict()
                q["content_type"] = quick_reply._type
                q["payload"] = quick_reply.payload
                q["external_payload"] = quick_reply.external_payload
                q["data"] = quick_reply.data
                if quick_reply.is_response:
                    q["ignore_for_webhook"] = False
                if isinstance(quick_reply, QuickReplyText):
                    q["title"] = quick_reply.title
                if not isinstance(quick_reply, QuickReplyLocation):
                    q["image_url"] = quick_reply.image_url
                xmd["quick_replies"].append(q)
            if len(self.quick_replies) == 1 and self.quick_replies[0].is_response:
                xmd["quick_replies"] = xmd["quick_replies"][0]
            data["platform_xmd"] = json.dumps(xmd)

        if self.reply_to_id:
            data["replied_to_message_id"] = self.reply_to_id

        return data

    @classmethod
    def _from_graphql(cls, data, client, thread_id, thread_type)-> Message:
        if data is None:
            return
        if data.get("message_sender") is None:
            data["message_sender"] = {}
        if data.get("message") is None:
            data["message"] = {}
        tags = data.get("tags_list")
        rtn = cls(
            text=data["message"].get("text"),
            mentions=[
                Mention(
                    m.get("entity", {}).get("id"),
                    offset=m.get("offset"),
                    length=m.get("length"),
                )
                for m in data["message"].get("ranges") or ()
            ],
            emoji_size=EmojiSize._from_tags(tags),
            sticker=_sticker.Sticker._from_graphql(data.get("sticker")),
        )
        rtn.forwarded = cls._get_forwarded_from_tags(tags)
        rtn.uid = str(data["message_id"])
        rtn.author = str(data["message_sender"]["id"])
        rtn.timestamp = data.get("timestamp_precise")
        rtn.unsent = False
        rtn.client = client
        rtn.thread_id = thread_id
        rtn.thread_type = thread_type
        if data.get("unread") is not None:
            rtn.is_read = not data["unread"]
        rtn.reactions = {
            str(r["user"]["id"]): MessageReaction._extend_if_invalid(r["reaction"])
            for r in data["message_reactions"]
        }
        if data.get("blob_attachments") is not None:
            rtn.attachments = [
                _file.graphql_to_attachment(attachment)
                for attachment in data["blob_attachments"]
            ]
        if data.get("platform_xmd_encoded"):
            quick_replies = json.loads(data["platform_xmd_encoded"]).get(
                "quick_replies"
            )
            if isinstance(quick_replies, list):
                rtn.quick_replies = [
                    graphql_to_quick_reply(q) for q in quick_replies
                ]
            elif isinstance(quick_replies, dict):
                rtn.quick_replies = [
                    graphql_to_quick_reply(quick_replies, is_response=True)
                ]
        if data.get("extensible_attachment") is not None:
            attachment = graphql_to_extensible_attachment(data["extensible_attachment"])
            if isinstance(attachment, _attachment.UnsentMessage):
                rtn.unsent = True
            elif attachment:
                rtn.attachments.append(attachment)
        if data.get("replied_to_message") is not None:
            rtn.replied_to = cls._from_graphql(data["replied_to_message"]["message"], client, thread_id, thread_type)
            print("this is replied_to: ", rtn.replied_to)
            if rtn.replied_to is not None:
                rtn.reply_to_id = rtn.replied_to.uid
        return rtn

    @classmethod
    def _from_reply(cls, data, client, thread_id, thread_type)-> Message:
        tags = data["messageMetadata"].get("tags")
        rtn = cls(
            text=data.get("body"),
            mentions=[
                Mention(m.get("i"), offset=m.get("o"), length=m.get("l"))
                for m in json.loads(data.get("data", {}).get("prng", "[]"))
            ],
            emoji_size=EmojiSize._from_tags(tags),
        )
        metadata = data.get("messageMetadata", {})
        rtn.forwarded = cls._get_forwarded_from_tags(tags)
        rtn.uid = metadata.get("messageId")
        rtn.author = str(metadata.get("actorFbId"))
        rtn.timestamp = metadata.get("timestamp")
        location = get_folder_tag(tags)
        if location:
            rtn.location = ThreadLocation._extend_if_invalid(location)
        rtn.client = client
        rtn.thread_id = thread_id
        rtn.thread_type = thread_type
        rtn.unsent = False
        if data.get("data", {}).get("platform_xmd"):
            quick_replies = json.loads(data["data"]["platform_xmd"]).get(
                "quick_replies"
            )
            if isinstance(quick_replies, list):
                if quick_replies is not None:
                    rtn.quick_replies = [
                    graphql_to_quick_reply(q) for q in quick_replies
                ]
            elif isinstance(quick_replies, dict):
                rtn.quick_replies = [
                    graphql_to_quick_reply(quick_replies, is_response=True)
                ]
        if data.get("attachments") is not None:
            for attachment in data["attachments"]:
                attachment = json.loads(attachment["mercuryJSON"])
                if attachment.get("blob_attachment"):
                    rtn.attachments.append(
                        _file.graphql_to_attachment(attachment["blob_attachment"])
                    )
                if attachment.get("extensible_attachment"):
                    extensible_attachment = graphql_to_extensible_attachment(
                        attachment["extensible_attachment"]
                    )
                    if isinstance(extensible_attachment, _attachment.UnsentMessage):
                        rtn.unsent = True
                    else:
                        rtn.attachments.append(extensible_attachment)
                if attachment.get("sticker_attachment"):
                    rtn.sticker = _sticker.Sticker._from_graphql(
                        attachment["sticker_attachment"]
                    )
        return rtn

    @classmethod
    def _from_pull(cls, data, mid: str , tags: List[str], author: str, timestamp: int , client, thread_id ,thread_type)-> Message:
        rtn = cls(text=data.get("body"))
        rtn.uid = mid
        rtn.author = author
        rtn.timestamp = timestamp
        rtn.client = client
        rtn.thread_id = thread_id
        rtn.thread_type = thread_type
        if data.get("messageMetadata"):
            rtn.location = ThreadLocation._extend_if_invalid(data["messageMetadata"]["folderId"]["systemFolderId"])
        if data.get("data") and data["data"].get("prng"):
            try:
                rtn.mentions = [
                    Mention(
                        str(mention.get("i")),
                        offset=mention.get("o"),
                        length=mention.get("l"),
                    )
                    for mention in _util.parse_json(data["data"]["prng"])
                ]
            except Exception:
                print("An exception occured while reading attachments")

        if data.get("attachments") and data.get("attachments") != []:
            try:
                for a in data["attachments"]:
                    mercury = a["mercury"]
                    if mercury.get("blob_attachment"):
                        image_metadata = a.get("imageMetadata", {})
                        attach_type = mercury["blob_attachment"]["__typename"]
                        attachment = _file.graphql_to_attachment(
                            mercury["blob_attachment"]
                        )

                        if attach_type in [
                            "MessageFile",
                            "MessageVideo",
                            "MessageAudio",
                        ]:
                            # TODO: Add more data here for audio files
                            print("this is attachment.size: ", int(a["fileSize"]))
                            attachment.size = int(a["fileSize"])
                        rtn.attachments.append(attachment)

                    elif mercury.get("sticker_attachment"):
                        rtn.sticker = _sticker.Sticker._from_graphql(
                            mercury["sticker_attachment"]
                        )

                    elif mercury.get("extensible_attachment"):
                        attachment = graphql_to_extensible_attachment(
                            mercury["extensible_attachment"]
                        )
                        if isinstance(attachment, _attachment.UnsentMessage):
                            rtn.unsent = True
                        elif attachment:
                            rtn.attachments.append(attachment)

            except Exception:
                print(
                    "An exception occured while reading attachments: {}".format(
                        data["attachments"]
                    )
                )
        rtn.emoji_size = EmojiSize._from_tags(tags)
        rtn.forwarded = cls._get_forwarded_from_tags(tags)
        return rtn


def get_folder_tag(tags):
    possible_values = ('inbox', 'archived', 'pending', 'other')
    for value in possible_values:
        if value in tags:
            return value.upper()
    return None

def graphql_to_extensible_attachment(data):
    story = data.get("story_attachment")
    if not story:
        return None

    target = story.get("target")
    if not target:
        return _attachment.UnsentMessage(uid=data.get("legacy_attachment_id"))

    _type = target["__typename"]
    if _type == "MessageLocation":
        return _location.LocationAttachment._from_graphql(story)
    elif _type == "MessageLiveLocation":
        return _location.LiveLocationAttachment._from_graphql(story)
    elif _type in ["ExternalUrl", "Story"]:
        return _attachment.ShareAttachment._from_graphql(story)

    return None
