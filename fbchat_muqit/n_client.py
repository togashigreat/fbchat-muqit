from __future__ import annotations
import asyncio
import json
import time
import random
from typing import Dict, List, Optional 

from .n_util import (
    now_time,
    mimetype_to_key,
    get_files_from_paths,
    require_list,
    prefix_url,
    get_files_from_urls
)

from .models import (
    Group, User, Page,
    Thread,
    ThreadType, 
    ThreadLocation,
    ThreadColor,
    ActiveStatus,
    Mention,
    Message,
    MessageReaction,
    LiveLocationAttachment,
    FBchatException,
    FBchatUserError
)

from ._graphql import (
    from_doc_id,
)
from .n_state import State
from .muqit import Mqtt


__all__ = ["Client"]

def generate_offline_threading_id():
    """Generate an offline threading ID."""
    return str(int(time.time() * 1000))


class Client:

    _listening = False
    
    @property
    def uid(self):
        """The Facebook ID of the client.
        """
        return self._uid
        
    def __init__(self, state: State):
        self._state: State = state
        self._uid = self._state.user_id
        self._default_thread_id: str | None = None
        self._default_thread_type: ThreadType | None = None
        self._markAlive = True
        self._buddylist = dict()
        self._mqtt: Mqtt | None = None
        self._wsReqNumber: int = 0
        self._wsTaskNumber: int = 0
        self._variance: float = 0 


    @classmethod
    async def startSession(cls, cookies_file_path: str)-> Client:
        """
        Log in Facebook using cookies and Return An instance of Client class to Interact with Facebook. 

        Args:
            file_path (str): The file path of Facebook cookies in json format.

        Returns:
            Client: An instance of Client class to interact with Facebook & Messenger.
        """
        try:
            state = await State.from_json_cookies(cookies_file_path)
            return cls(state=state)
        except Exception as e:
            raise RuntimeError("Failed to log in Facebook: ", e)

    async def getSession(self)-> Dict:
        """Returns Session Cookies"""
        return self._state.get_cookies()
            
    """
    INTERNAL REQUEST METHODS
    """

    async def _get(self, url, params):
        return await self._state._get(url, params)

    async def _post(self, url, params, files=None):
        return await self._state._post(url, params, files=files)

    async def _payload_post(self, url, data, files=None):
        return await self._state._payload_post(url, data, files=files)

    async def _graphql_requests(self, *queries):

        return tuple(await self._state._graphql_requests(*queries))

    async def _graphql_request(self, query):
        """Shorthand for ``graphql_requests(query)[0]``.

        Raises:
            FBchatException: If request failed
        """
        data = await self._graphql_requests(query)
        return data[0]

    """
    END INTERNAL REQUEST METHODS
    """

    """
    LOGIN METHODS
    """

    async def isLoggedIn(self)-> bool:
        """Send a request to Facebook to check the login status.

        Returns:
            bool: True if the client is still logged in Facebook.
        """
        return await self._state.is_logged_in()

    """
    DEFAULT THREAD METHODS
    """

    async def setActiveMessenger(self, status_on: bool = True):
        """Sets messenger Status Active if True or Inactive if False By default It is True

        Args:
            status_on: (bool): Whether to set status active or not. 
        """
        data = { 
            "online_policy": "BLOCKLIST",
            "web_allowlist": None,
            "web_blocklist": None,
            "web_visibility": status_on,
            "actor_id": str(self.uid),
            "client_mutation_id": "0",
            }

        doc_id = 5318370848213638

        data = {
            "doc_id": doc_id, "variables": json.dumps({"input": data})
        }
        await self._payload_post("/webgraphql/mutation", data)

    # async def sendActivte(self):
    #     data = {
    #         "fb_api_caller_class": "RelayModern",
    #         "fb_api_req_friendly_name": "MWChatSettingsQuery",
    #         "variables": {},
    #         "server_timestamps": True,
    #         "doc_id": "5248437728509060",
    #         "dpr": 3
    #     }
    #     await self._post(prefix_url("/api/graphql"), data)


    async def updateActiveMutation(self):
        """
        Updates User Last Active Status.

        Warning: Test Don't Use this.
        """
        variables = {
            "input": {
                "actor_id": str(self.uid),
                "client_mutation_id":"0"
            }
        }

        data = {
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": "UpdateUserLastActiveMutation",
            "variables": json.dumps(variables),
            "doc_id": 4844391925651372
        }
        await self._payload_post("/webgraphql/mutation", data)

    def _getThread(self, given_thread_id=None, given_thread_type=None):
        """Check if thread ID is given and if default is set, and return correct values.

        Returns:
            tuple: Thread ID and thread type

        Raises:
            ValueError: If thread ID is not given and there is no default
        """
        if given_thread_id is None:
            if self._default_thread_id is not None:
                return self._default_thread_id, self._default_thread_type
            else:
                raise ValueError("Thread ID is not set")
        else:
            return given_thread_id, given_thread_type


    def _setDefaultThread(self, thread_id, thread_type):
        """Set default thread to send messages to.

        Args:
            thread_id: User/Group ID to default to. See :ref:`intro_threads`
            thread_type (ThreadType): See :ref:`intro_threads`
        """
        self._default_thread_id = thread_id
        self._default_thread_type = thread_type

    def _resetDefaultThread(self):
        # """Reset default thread."""
        self._setDefaultThread(None, None)

    """
    END DEFAULT THREAD METHODS
    """

    """
    FETCH METHODS
    """

    async def _forcedFetch(self, thread_id, mid):
        params = {"thread_and_message_id": {"thread_id": thread_id, "message_id": mid}}
        (j,) = await self._graphql_requests(from_doc_id("1768656253222505", params))
        return j


    async def _fetchInfo(self, *ids):
        data = {"ids[{}]".format(i): _id for i, _id in enumerate(ids)}
        j = await self._payload_post("/chat/user_info/", data)

        if j.get("profiles") is None:
            raise FBchatException("No users/pages returned: {}".format(j))

        entries = {}
        for _id in j["profiles"]:
            k = j["profiles"][_id]
            if k["type"] in ["user", "friend"]:
                entries[_id] = {
                    "id": _id,
                    "type": ThreadType.USER,
                    "url": k.get("uri"),
                    "first_name": k.get("firstName"),
                    "is_viewer_friend": k.get("is_friend"),
                    "gender": k.get("gender"),
                    "profile_picture": {"uri": k.get("thumbSrc")},
                    "name": k.get("name"),
                }
            elif k["type"] == "page":
                entries[_id] = {
                    "id": _id,
                    "type": ThreadType.PAGE,
                    "url": k.get("uri"),
                    "profile_picture": {"uri": k.get("thumbSrc")},
                    "name": k.get("name"),
                }
            else:
                raise FBchatException(
                    "{} had an unknown thread type: {}".format(_id, k)
                )

    
        return entries

    async def fetchThreads(self, thread_location, before=None, after=None, limit=None)-> List[Thread]:
        """Fetch all threads in ``thread_location``.

        Threads will be sorted from newest to oldest.

        Args:
            thread_location (ThreadLocation): INBOX, PENDING, ARCHIVED or OTHER
            before: Fetch only thread before this epoch (in ms) (default all threads)
            after: Fetch only thread after this epoch (in ms) (default all threads)
            limit: The max. amount of threads to fetch (default all threads)

        Returns:
            List[Thread]: A List of Thread objects with Thread info

        Raises:
            FBchatException: If request failed
        """
        threads = []

        last_thread_timestamp = None
        while True:
            # break if limit is exceeded
            if limit and len(threads) >= limit:
                break

            # fetchThreadList returns at max 20 threads before last_thread_timestamp (included)
            candidates = await self.fetchThreadList(
                before=last_thread_timestamp, thread_location=thread_location
            )

            if len(candidates) > 1:
                threads += candidates[1:]
            else:  # End of threads
                break

            last_thread_timestamp = threads[-1].last_message_timestamp

            # FB returns a sorted list of threads
            if (before is not None and int(last_thread_timestamp) > before) or (
                after is not None and int(last_thread_timestamp) < after
            ):
                break

        # Return only threads between before and after (if set)
        if before is not None or after is not None:
            for t in threads:
                last_message_timestamp = int(t.last_message_timestamp)
                if (before is not None and last_message_timestamp > before) or (
                    after is not None and last_message_timestamp < after
                ):
                    threads.remove(t)

        if limit and len(threads) > limit:
            return threads[:limit]

        return threads

    async def fetchAllUsersFromThreads(self, threads)->List[User]:
        """Fetch all users involved in given threads.
        Sometimes It may fail to fetch if user is blocked.
        It will be fixed later on.

        Args:
            threads: Thread: List of threads to check for users

        Returns:
            List[User]:  Returns list of User object with User Info.

        Raises:
            FBchatException: If request failed
        """
        users = []
        users_to_fetch = []  # It's more efficient to fetch all users in one request
        for thread in threads:
            if thread.type == ThreadType.USER:
                if thread.uid not in [user.uid for user in users]:
                    users.append(thread)
            elif thread.type == ThreadType.GROUP:
                for user_id in thread.participants:
                    if (
                        user_id not in [user.uid for user in users]
                        and user_id not in users_to_fetch
                    ):
                        users_to_fetch.append(user_id)

        to_fetch_users = await self.fetchUserInfo(*users_to_fetch)
        for user_id, user in to_fetch_users.items():
            users.append(user)
        return users

    async def fetchAllUsers(self):
        """Fetch all users the Client is currently chatting with.

        Returns:
            List[User]:  User objects with Users info

        Raises:
            FBchatException: If request failed
        """
        data = {"viewer": self._uid}
        j = await self._payload_post("/chat/user_info_all", data)

        users = []
        for data in j.values():
            if data["type"] in ["user", "friend"]:
                if data["id"] in ["0", 0]:
                    # Skip invalid users
                    continue
                users.append(User._from_all_fetch(data))
        return users

    async def fetchUserInfo(self, *user_ids)-> Dict[str, User]:
        """Fetch users' info from IDs, unordered.

        Warning:
            Sends two requests, to fetch all available info!

        Args:
            user_ids: One or more user ID(s) to fetch

        Returns:
            Dict[str, User]: Returns Dict with User objects, labeled by their ID.

        Raises:
            FBchatException: If request failed
        """
        threads = await self.fetchThreadInfo(*user_ids)
        users = {}
        for id_, thread in threads.items():
            if thread.type == ThreadType.USER:
                users[id_] = thread
            else:
                raise FBchatUserError("Thread {} was not a user".format(thread))

        return users


    async def fetchGroupInfo(self, *group_ids)-> Dict[str, Group]:
        """Fetch groups' info from IDs, unordered.

        Args:
            group_ids (str | List[str]): One or more group ID(s) to query

        Returns:
            Dict[str, Group]:  objects, labeled by their ID

        Raises:
            FBchatException: If request failed
        """
        threads = await self.fetchThreadInfo(*group_ids)
        groups = {}
        for id_, thread in threads.items():
            if thread.type == ThreadType.GROUP:
                groups[id_] = thread
            else:
                raise FBchatUserError("Thread {} was not a group".format(thread))

        return groups

    async def fetchThreadInfo(self, *thread_ids)-> Dict[str, Thread]:
        """Fetch threads' info from IDs, unordered.

        Warning:
            Sends two requests if users or pages are present, to fetch all available info!

        Args:
            thread_ids (str | List[str]): One or more thread ID(s) to query

        Returns:
            Dict[str, Thread]: Thread objects, labeled by their ID. It can User/Group/Page Thread.

        Raises:
            FBchatException: If request failed
        """
        queries = []
        for thread_id in thread_ids:
            params = {
                "id": thread_id,
                "message_limit": 0,
                "load_messages": False,
                "load_read_receipts": False,
                "before": None,
            }
            queries.append(from_doc_id("2147762685294928", params))

        j = []
        for q in queries:
            try:
                data = await self._graphql_request(q)
                j.append(data)
            except Exception as e:
                print("Couldn't fetch User/Thread. Thread or User is either doesn't exist/deactivatedor blocked in Facebook. ID: ", q["query_params"]["id"])
        for i, entry in enumerate(j):
            if entry.get("message_thread") is None:
                # If you don't have an existing thread with this person, attempt to retrieve user data anyways
                j[i]["message_thread"] = {
                    "thread_key": {"other_user_id": thread_ids[i]},
                    "thread_type": "ONE_TO_ONE",
                }

        pages_and_user_ids = [
            k["message_thread"]["thread_key"]["other_user_id"]
            for k in j
            if k["message_thread"].get("thread_type") == "ONE_TO_ONE"
        ]
        pages_and_users = {}
        if len(pages_and_user_ids) != 0:
            pages_and_users = await self._fetchInfo(*pages_and_user_ids)

        rtn = {}
        for i, entry in enumerate(j):
            entry = entry["message_thread"]
            if entry.get("thread_type") == "GROUP":
                _id = entry["thread_key"]["thread_fbid"]
                rtn[_id] = Group._from_graphql(entry)
            elif entry.get("thread_type") == "ONE_TO_ONE":
                _id = entry["thread_key"]["other_user_id"]
                if pages_and_users.get(_id) is None:
                    raise FBchatException("Could not fetch thread {}".format(_id))
                entry.update(pages_and_users[_id])
                if entry["type"] == ThreadType.USER:
                    rtn[_id] = User._from_graphql(entry)
                else:
                    rtn[_id] = Page._from_graphql(entry)
            else:
                raise FBchatException(
                    "{} had an unknown thread type: {}".format(thread_ids[i], entry)
                )

        return rtn

    async def fetchThreadMessages(self, thread_id=None, limit=20, before=None):
        """Fetch messages in a thread, ordered by most recent.

        Args:
            thread_id (str): User/Group ID to get messages from. See :ref:`intro_threads`
            limit (int): Max. number of messages to retrieve
            before (Optional[int]): A timestamp, indicating from which point to retrieve messages

        Returns:
            List[Message]: Returns List of Message object with message info.

        Raises:
            FBchatException: If request failed
        """
        thread_id, thread_type = self._getThread(thread_id, None)

        params = {
            "id": thread_id,
            "message_limit": limit,
            "load_messages": True,
            "load_read_receipts": True,
            "before": before,
        }
        (j,) = await self._graphql_requests(from_doc_id("1860982147341344", params))

        if j.get("message_thread") is None:
            raise FBchatException("Could not fetch thread {}: {}".format(thread_id, j))

        messages = [
            Message._from_graphql(message, self, thread_id, thread_type)
            for message in j["message_thread"]["messages"]["nodes"]
        ]
        messages.reverse()

        read_receipts = j["message_thread"]["read_receipts"]["nodes"]

        for message in messages:
            for receipt in read_receipts:
                if int(receipt["watermark"]) >= int(message.timestamp):
                    message.read_by.append(receipt["actor"]["id"])

        return messages

    async def fetchThreadList(
        self, limit=20, thread_location=ThreadLocation.INBOX, before=None
    )->List[Thread]:
        """Fetch the client's thread list.

        Args:
            limit (int): Max. number of threads to retrieve. Capped at 20
            thread_location (ThreadLocation): INBOX, PENDING, ARCHIVED or OTHER
            before (int): A timestamp (in milliseconds), indicating from which point to retrieve threads

        Returns:
            List[Thread]: Returns a List of Thread objects.

        Raises:
            FBchatException: If request failed
        """

        if limit > 20 or limit < 1:
            raise FBchatUserError("`limit` should be between 1 and 20")

        if thread_location in ThreadLocation:
            loc_str = thread_location.value
        else:
            raise FBchatUserError('"thread_location" must be a value of ThreadLocation')

        params = {
            "limit": limit,
            "tags": [loc_str],
            "before": before,
            "includeDeliveryReceipts": True,
            "includeSeqID": False,
        }
        (j,) = await self._graphql_requests(from_doc_id("1349387578499440", params))

        rtn = []
        for node in j["viewer"]["message_threads"]["nodes"]:
            _type = node.get("thread_type")
            if _type == "GROUP":
                rtn.append(Group._from_graphql(node))
            elif _type == "ONE_TO_ONE":
                rtn.append(User._from_thread_fetch(node))
            else:
                raise FBchatException(
                    "Unknown thread type: {}, with data: {}".format(_type, node)
                )
        return rtn


    async def fetchMessageInfo(self, mid, thread_id=None):
        """Fetch `Message` object from the given message id.

        Args:
            mid (str): Message ID to fetch from
            thread_id (str): User/Group ID to get message info from. See :ref:`intro_threads`

        Returns:
            Message: Returns a Message object.

        Raises:
            FBchatException: If request failed
        """
        thread_id, thread_type = self._getThread(thread_id, None)
        message_info = await self._forcedFetch(thread_id, mid).get("message")
        return Message._from_graphql(message_info, self, thread_id, thread_type)


    
    def getUserActiveStatus(self, user_id):
        """Fetch friend active status as an `ActiveStatus` object.

        Return ``None`` if status isn't known.

        Warning:
            Only works when listening.

        Args:
            user_id (str): ID of the user

        Returns:
            ActiveStatus: Given user active status
        """
        return self._buddylist.get(str(user_id))

    """
    END FETCH METHODS
    """

    """
    SEND METHODS
    """

    def _oldMessage(self, message):
        return message if isinstance(message, Message) else Message(text=message)

    async def _doSendRequest(self, data, get_thread_id=False):
        # """Send the data to `SendURL`, and returns the message ID or None on failure."""
        mid, thread_id = await self._state.do_send_request(data)
        if get_thread_id:
            return mid, thread_id
        else:
            return mid

    async def send(self, message, thread_id=None, thread_type=ThreadType.USER):
        """Send message to a thread.

        Args:
            message (Message): Message object with message information (e.g. text, image, sticker, reply_to etc.)
            thread_id (str): User/Group ID to send to. See :ref:`intro_threads`
            thread_type (ThreadType): See ThreadType

        Returns:
            :ref:`Message ID <intro_message_ids>` of the sent message

        Raises:
            FBchatException: If request failed
        """
        thread_id, thread_type = self._getThread(thread_id, thread_type)
        thread = thread_type._to_class()(thread_id)
        data = thread._to_send_data()
        data.update(message._to_send_data())
        return await self._doSendRequest(data)

    async def sendMessage(self, message: str, thread_id: str, thread_type = ThreadType.USER, reply_to_id: Optional[str] = None , mentions: Optional[List[str]] = None):
        """ Send message easily to messenger using this method.

        Args:
            message: the text message you want to send 
            thread_id: The thread message to send 
            thread_type: Type of the thread
            reply_to_id: ID of The message you want to reply
            mentions: List of users uid to mention messages are automatically formatted.
        """
        
        messageData = Message(text=message, reply_to_id=reply_to_id)
        if mentions and thread_type == ThreadType.GROUP:
            to_mentions = [asyncio.create_task(self.fetchUserInfo(id)) for id in mentions]
            mention_msg = ""
            fetched_users = await asyncio.gather(*to_mentions)
            fetched_name_id = [(user.name, user.uid) for userDict in fetched_users for user in userDict.values()]
            mentionList: List[Mention] = []
            for user in fetched_name_id:
                mentionList.append(Mention(
                        thread_id=user[1],
                        offset=len(mention_msg),
                        length=len(user[0])+1  #type: ignore 
                    ))
                mention_msg += f"@{user[0]} "

            message = f"{mention_msg}{message}"
            messageData = Message(text=message, reply_to_id=reply_to_id, mentions=mentionList)
        return await self.send(messageData, thread_id, thread_type)

    async def shareContact(self, message: str, sender_id: str, thread_id: str):
        """
        Shares Messenger Contact with others using.

        Args:
            message (str): The message you want to send along with contact.
            sender_id (str): The ID of the User Contact to share.
            thread_id (str): The Thread ID to share the contact.
        """
        self._wsReqNumber += 1 
        self._wsTaskNumber += 1 
        query_payload = {
        "contact_id": sender_id,
        "sync_group": 1,
        "text": message or "",
        "thread_id": thread_id,
        }
        query = {
        "failure_count": None,
        "label": "359",
        "payload": json.dumps(query_payload),
        "queue_name": "messenger_contact_sharing",
        "task_id": int(random.random() * 1001),
        }
        context = {
        "app_id": "2220391788200892",
        "payload": json.dumps({
            "tasks": [query],
            "epoch_id": generate_offline_threading_id(),
            "version_id": "7214102258676893",
        }),
        "request_id": self._wsReqNumber,
        "type": 3,
        }
        if self._mqtt:
            await self._mqtt._mqttClient.publish(topic="/ls_req", payload=json.dumps(context), qos=1)

    def _epoch_id(self):
        self._variance = (self._variance + 0.1) % 5
        return int(now_time() * (4194304 + self._variance))


    async def sendMessageMqqtt(self, msg, thread_id, reply_to_message: Optional[str] = None):
        """
        send messages through mqtt protocol. To reply to a message pass message ID. 
        It works same way as  ``sendMessage()`` method.

        Args:
            msg (str): The message you want to send.
            thread_id (str): The thread you want to message. 
            reply_to_message (str): If you want to reply to a message pass the ``mid`` message ID.
        """
        if isinstance(msg, str):
            msg = {"body": msg}
        elif not isinstance(msg, dict):
            raise ValueError("Message must be a string or dictionary.")

        timestamp = int(now_time())
        epoch = timestamp << 22
        otid = epoch + random.randint(0, 4194304)

        form = {
            "app_id": "2220391788200892",
            "payload": {
                "tasks": [
                    {
                        "label": "46",
                        "payload": {
                            "thread_id": str(thread_id),
                            "otid": str(otid),
                            "source": 0,
                            "send_type": 1,
                            "sync_group": 1,
                            "text": msg.get("body", ""),
                            "initiating_source": 1,
                            "skip_url_preview_gen": 0,
                        },
                        "queue_name": str(thread_id),
                        "task_id": 0,
                        "failure_count": None,
                    },
                    {
                        "label": "21",
                        "payload": {
                            "thread_id": str(thread_id),
                            "last_read_watermark_ts": timestamp,
                            "sync_group": 1,
                        },
                        "queue_name": str(thread_id),
                        "task_id": 1,
                        "failure_count": None,
                    },
                ],
                "epoch_id": self._epoch_id(),
                "version_id": "6120284488008082",
                "data_trace_id": None,
            },
            "request_id": 1,
            "type": 3,
        }
        await self._send(form, thread_id, reply_to_message)

    async def _send(self, form, thread_id, reply_to_message):
          # Assumes MQTT client is part of the State class
        if reply_to_message:
            form["payload"]["tasks"][0]["payload"]["reply_metadata"] = {
                "reply_source_id": reply_to_message,
                "reply_source_type": 1,
                "reply_type": 0,
            }

        for task in form["payload"]["tasks"]:
            task["payload"] = json.dumps(task["payload"])

        form["payload"] = json.dumps(form["payload"])
        topic = "/ls_req"
        message = json.dumps(form)

        try:
            if self._mqtt:
                await self._mqtt._mqttClient.publish(topic, message, qos=1)
        except Exception as e:
            print("error: ", e)

    async def unsend(self, mid):
        """Unsend message by it's ID (removes it for everyone).

        Args:
            mid: :ref:`Message ID <intro_message_ids>` of the message to unsend
        """
        data = {"message_id": mid}
        await self._payload_post("/messaging/unsend_message/?dpr=1", data)


    async def _upload(self, files, voice_clip=False):
        return await self._state._upload(files, voice_clip=voice_clip)

    async def _sendFiles(
        self, files, message=None, thread_id=None, thread_type=ThreadType.USER
    ):
        # """Send files from file IDs to a thread.
        #
        # `files` should be a list of tuples, with a file's ID and mimetype.
        # """
        thread_id, thread_type = self._getThread(thread_id, thread_type)
        thread = thread_type._to_class()(thread_id)
        data = thread._to_send_data()
        data.update(self._oldMessage(message)._to_send_data())
        data["action_type"] = "ma-type:user-generated-message"
        data["has_attachment"] = True

        for i, (file_id, mimetype) in enumerate(files):
            data["{}s[{}]".format(mimetype_to_key(mimetype), i)] = file_id
        try:    
            return await self._doSendRequest(data)
        except Exception as e:
            raise ValueError("Got wrong response: ", e)

    async def sendLocalFiles(
        self, file_paths, message=None, thread_id=None, thread_type=ThreadType.USER
    ):
        """Send local files to a thread.

        Args:
            file_paths (str): Paths of files to upload and send
            message (str): Additional message
            thread_id (str): User/Group ID to send to. See :ref:`intro_threads`
            thread_type (ThreadType): See :ref:`intro_threads`

        Returns:
            :ref:`Message ID <intro_message_ids>` of the sent files

        Raises:
            FBchatException: If request failed
        """
        
        file_paths = require_list(file_paths)
        with get_files_from_paths(file_paths) as x:
            files = await self._upload(x)
        return await self._sendFiles(
            files=files, message=message, thread_id=thread_id, thread_type=thread_type
        )


    async def sendRemoteFiles(
        self, file_urls, message=None, thread_id=None, thread_type=ThreadType.USER
    ):
        """Send files from URLs to a thread.

        Args:
            file_urls (List[str]): URLs of files to upload and send
            message (str): Additional message
            thread_id (str): User/Group ID to send to. See :ref:`intro_threads`
            thread_type (ThreadType): See :ref:`intro_threads`

        Returns:
            :ref:`Message ID <intro_message_ids>` of the sent files

        Raises:
            FBchatException: If request failed
        """
        file_urls = require_list(file_urls)
        files = await self._upload(await get_files_from_urls(file_urls))
        return await self._sendFiles(files=files, message=message, thread_id=thread_id, thread_type=thread_type)


    async def sendLocalVoiceClips(
        self, clip_paths, message=None, thread_id=None, thread_type=ThreadType.USER
    ):
        """Send local voice clips to a thread.

        Args:
            clip_paths (str): Paths of clips to upload and send
            message (str): Additional message
            thread_id (str): User/Group ID to send to. See :ref:`intro_threads`
            thread_type (ThreadType): See :ref:`intro_threads`

        Returns:
            :ref:`Message ID <intro_message_ids>` of the sent files

        Raises:
            FBchatException: If request failed
        """
        clip_paths = require_list(clip_paths)
        with get_files_from_paths(clip_paths) as x:
            files = await self._upload(x, voice_clip=True)
        return await self._sendFiles(
            files=files, message=message, thread_id=thread_id, thread_type=thread_type
        )


    async def sendImage(
        self,
        image_id,
        message=None,
        thread_id=None,
        thread_type=ThreadType.USER,
        is_gif=False,
    ):
        """Deprecated. Use `sendLocalFiles()` instead."""
        if is_gif:
            mimetype = "image/gif"
        else:
            mimetype = "image/png"
        return await self._sendFiles(
            files=[(image_id, mimetype)],
            message=message,
            thread_id=thread_id,
            thread_type=thread_type,
        )


    """ Messenger GROUP Method Starts """

    async def addUsersToGroup(self, user_ids, thread_id=None):
        """Add users to a group.

        Args:
            user_ids (List[str]): One or more user IDs to add
            thread_id (str): Group ID to add people to. See :ref:`intro_threads`

        Raises:
            FBchatException: If request failed
        """
        thread_id, thread_type = self._getThread(thread_id, None)
        data = Group(thread_id)._to_send_data()

        data["action_type"] = "ma-type:log-message"
        data["log_message_type"] = "log:subscribe"

        user_ids = require_list(user_ids)

        for i, user_id in enumerate(user_ids):
            if user_id == self._uid:
                raise FBchatUserError(
                    "Error when adding users: Cannot add self to group thread"
                )
            else:
                data[
                    "log_message_data[added_participants][{}]".format(i)
                ] = f"fbid:{user_id}"

        return await self._doSendRequest(data)



    async def removeUserFromGroup(self, user_id, thread_id=None):
        """Remove user from a group.

        Args:
            user_id: User ID to remove
            thread_id: Group ID to remove people from. See :ref:`intro_threads`

        Raises:
            FBchatException: If request failed
        """
        thread_id, thread_type = self._getThread(thread_id, None)

        data = {"uid": user_id, "tid": thread_id}
        await self._payload_post("/chat/remove_participants/", data)



    async def _adminStatus(self, admin_ids, admin, thread_id=None):
        thread_id, thread_type = self._getThread(thread_id, None)

        data = {"add": admin, "thread_fbid": thread_id}

        admin_ids = require_list(admin_ids)

        for i, admin_id in enumerate(admin_ids):
            data[f"admin_ids[{i}]"] = str(admin_id)

        await self._payload_post("/messaging/save_admins/?dpr=1", data)

    async def addGroupAdmins(self, admin_ids: str | List[str], thread_id=None):
        """Set specified users as group admins.

        Args:
            admin_ids (str): One or more user IDs to set admin
            thread_id (str): Group ID to remove people from. See :ref:`intro_threads`

        Raises:
            FBchatException: If request failed
        """
        await self._adminStatus(admin_ids, True, thread_id)

    async def removeGroupAdmins(self, admin_ids: str | List[str], thread_id=None):
        """Remove admin status from specified users.

        Args:
            admin_ids (str): One or more user IDs to remove admin
            thread_id (str): Group ID to remove people from. See :ref:`intro_threads`

        Raises:
            FBchatException: If request failed
        """
        await self._adminStatus(admin_ids, False, thread_id)

    async def changeGroupApprovalMode(self, require_admin_approval: bool, thread_id=None):
        """Change group's approval mode.

        Args:
            require_admin_approval (bool): True or False
            thread_id (str): Group ID to remove people from. See :ref:`intro_threads`

        Raises:
            FBchatException: If request failed
        """
        thread_id, thread_type = self._getThread(thread_id, None)

        data = {"set_mode": int(require_admin_approval), "thread_fbid": thread_id}
        j = self._payload_post("/messaging/set_approval_mode/?dpr=1", data)

    async def _usersApproval(self, user_ids, approve, thread_id=None):
        thread_id, thread_type = self._getThread(thread_id, None)

        user_ids = list(require_list(user_ids))

        data = {
            "client_mutation_id": "0",
            "actor_id": self._uid,
            "thread_fbid": thread_id,
            "user_ids": user_ids,
            "response": "ACCEPT" if approve else "DENY",
            "surface": "ADMIN_MODEL_APPROVAL_CENTER",
        }
        await self._graphql_requests(from_doc_id("1574519202665847", {"data": data}))


    async def acceptUsersToGroup(self, user_ids: str | List[str], thread_id=None):
        """Accept users to the group from the group's approval.

        Args:
            user_ids (List(str)): One or more user IDs to accept
            thread_id (str): Group ID to accept users to. See :ref:`intro_threads`

        Raises:
            FBchatException: If request failed
        """
        await self._usersApproval(user_ids, True, thread_id)

    async def denyUsersFromGroup(self, user_ids: str | List[str], thread_id=None):
        """Deny users from joining the group.

        Args:
            user_ids (List[str]): One or more user IDs to deny
            thread_id (str): Group ID to deny users from. See :ref:`intro_threads`

        Raises:
            FBchatException: If request failed
        """
        await self._usersApproval(user_ids, False, thread_id)


    async def _changeGroupImage(self, image_id, thread_id=None):
        # """Change a thread image from an image id.
        #
        # Args:
        #     image_id: ID of uploaded image
        #     thread_id: User/Group ID to change image. See :ref:`intro_threads`
        #
        # Raises:
        #     FBchatException: If request failed
        # """
        thread_id, thread_type = self._getThread(thread_id, None)

        data = {"thread_image_id": image_id, "thread_id": thread_id}

        await self._payload_post("/messaging/set_thread_image/?dpr=1", data)

    async def changeGroupImageRemote(self, image_url, thread_id=None):
        """Change a thread image from a URL.

        Args:
            image_url: URL of an image to upload and change
            thread_id: User/Group ID to change image. See :ref:`intro_threads`

        Raises:
            FBchatException: If request failed
        """
        ((image_id, mimetype),) = await self._upload(await get_files_from_urls([image_url]))
        return await self._changeGroupImage(image_id, thread_id)

    async def changeGroupImageLocal(self, image_path, thread_id=None):
        """Change a thread image from a local path.

        Args:
            image_path: Path of an image to upload and change
            thread_id: User/Group ID to change image. See :ref:`intro_threads`

        Raises:
            FBchatException: If request failed
        """
        with get_files_from_paths([image_path]) as files:
            ((image_id, mimetype),) = await self._upload(files)

        return await self._changeGroupImage(image_id, thread_id)

    async def changeThreadTitle(self, title, thread_id=None, thread_type=ThreadType.USER):
        """Change title of a thread.

        If this is executed on a user thread, this will change the nickname of that
        user, effectively changing the title.

        Args:
            title: New group thread title
            thread_id: Group ID to change title of. See :ref:`intro_threads`
            thread_type (ThreadType): See :ref:`intro_threads`

        Raises:
            FBchatException: If request failed
        """
        thread_id, thread_type = self._getThread(thread_id, thread_type)

        if thread_type == ThreadType.USER:
            # The thread is a user, so we change the user's nickname
            return await self.changeNickname(
                title, thread_id, thread_id=thread_id, thread_type=thread_type
            )

        data = {"thread_name": title, "thread_id": thread_id}
        await self._payload_post("/messaging/set_thread_name/?dpr=1", data)

    async def changeNickname(
        self, nickname, user_id, thread_id=None, thread_type=ThreadType.USER
    ):
        """Change the nickname of a user in a thread.

        Args:
            nickname: New nickname
            user_id: User that will have their nickname changed
            thread_id: User/Group ID to change color of. See :ref:`intro_threads`
            thread_type (ThreadType): See :ref:`intro_threads`

        Raises:
            FBchatException: If request failed
        """
        thread_id, thread_type = self._getThread(thread_id, thread_type)

        data = {
            "nickname": nickname,
            "participant_id": user_id,
            "thread_or_other_fbid": thread_id,
        }
        await self._payload_post(
            "/messaging/save_thread_nickname/?source=thread_settings&dpr=1", data
        )

    async def changeThreadColor(self, color, thread_id=None):
        """Change thread color.

        Args:
            color (ThreadColor): New thread color
            thread_id: User/Group ID to change color of. See :ref:`intro_threads`

        Raises:
            FBchatException: If request failed
        """
        thread_id, thread_type = self._getThread(thread_id, None)

        data = {
            "color_choice": color.value if color != ThreadColor.MESSENGER_BLUE else "",
            "thread_or_other_fbid": thread_id,
        }
        await self._payload_post(
            "/messaging/save_thread_color/?source=thread_settings&dpr=1", data
        )

    async def changeThreadEmoji(self, emoji, thread_id=None):
        """Change thread color.

        Note:
            While changing the emoji, the Facebook web client actually sends multiple
            different requests, though only this one is required to make the change.

        Args:
            color: New thread emoji
            thread_id: User/Group ID to change emoji of. See :ref:`intro_threads`

        Raises:
            FBchatException: If request failed
        """
        thread_id, thread_type = self._getThread(thread_id, None)

        data = {"emoji_choice": emoji, "thread_or_other_fbid": thread_id}
        await self._payload_post(
            "/messaging/save_thread_emoji/?source=thread_settings&dpr=1", data
        )


    async def reactToMessage(self, message_id, reaction):
        """React to a message, or removes reaction.

        Args:
            message_id: :ref:`Message ID <intro_message_ids>` to react to
            reaction (MessageReaction): Reaction emoji to use, if None removes reaction

        Raises:
            FBchatException: If request failed
        """
        data = {
            "action": "ADD_REACTION" if reaction else "REMOVE_REACTION",
            "client_mutation_id": "1",
            "actor_id": self._uid,
            "message_id": str(message_id),
            "reaction": reaction.value if reaction else None,
        }
        data = {"doc_id": 1491398900900362, "variables": json.dumps({"data": data})}
        await self._payload_post("/webgraphql/mutation", data)
    """

    End Messenger GROUP methods

    """

    """

    Facebook USER utils

    """


    async def friendConnect(self, friend_id):
        """
        Sends friend request by User ID
        """
        data = {"to_friend": friend_id, "action": "confirm"}

        await self._payload_post("/ajax/add_friend/action.php?dpr=1", data)

    async def removeFriend(self, friend_id=None):
        """Remove a specified friend from the client's friend list.

        Args:
            friend_id: The ID of the friend that you want to remove

        Returns:
            True

        Raises:
            FBchatException: If request failed
        """
        data = {"uid": friend_id}
        await self._payload_post("/ajax/profile/removefriendconfirm.php", data)
        return True

    async def blockUser(self, user_id):
        """Block messages from a specified user.

        Args:
            user_id: The ID of the user that you want to block

        Returns:
            True

        Raises:
            FBchatException: If request failed
        """
        data = {"fbid": user_id}
        await self._payload_post("/messaging/block_messages/?dpr=1", data)
        return True

    async def unblockUser(self, user_id):
        """Unblock a previously blocked user.

        Args:
            user_id: The ID of the user that you want to unblock

        Returns:
            Whether the request was successful

        Raises:
            FBchatException: If request failed
        """
        data = {"fbid": user_id}
        await self._payload_post("/messaging/unblock_messages/?dpr=1", data)
        return True


    async def setTypingStatus(self, status, thread_id=None, thread_type=None):
        """Set users typing status in a thread.

        Args:
            status (TypingStatus): Specify the typing status
            thread_id: User/Group ID to change status in. See :ref:`intro_threads`
            thread_type (ThreadType): See :ref:`intro_threads`

        Raises:
            FBchatException: If request failed
        """
        thread_id, thread_type = self._getThread(thread_id, thread_type)

        data = {
            "typ": status.value,
            "thread": thread_id,
            "to": thread_id if thread_type == ThreadType.USER else "",
            "source": "mercury-chat",
        }
        await self._payload_post("/ajax/messaging/typ.php", data)

    async def markAsSeen(self):
        """Deprecated"""

        await self._payload_post("/ajax/mercury/mark_seen.php", {"seen_timestamp": now_time()})

    async def markAsReadAll(self):
        """Marks all messages as Read"""
        form = {
            "folder": "inbox"
        }
        await self._payload_post(prefix_url("/ajax/mercury/mark_folder_as_read.php"), form)
    ### Thread Utils ###

    async def moveThreads(self, location, thread_ids):
        """Move threads to specified location.

        Args:
            location (ThreadLocation): INBOX, PENDING, ARCHIVED or OTHER
            thread_ids: Thread IDs to move. See :ref:`intro_threads`

        Returns:
            True

        Raises:
            FBchatException: If request failed
        """
        thread_ids = require_list(thread_ids)

        if location == ThreadLocation.PENDING:
            location = ThreadLocation.OTHER

        if location == ThreadLocation.ARCHIVED:
            data_archive = dict()
            data_unpin = dict()
            for thread_id in thread_ids:
                data_archive[f"ids[{thread_id}]"] = "true"
                data_unpin[f"ids[{thread_id}]"] = "false"
            j_archive = await self._payload_post(
                "/ajax/mercury/change_archived_status.php?dpr=1", data_archive
            )
            j_unpin = await self._payload_post(
                "/ajax/mercury/change_pinned_status.php?dpr=1", data_unpin
            )
        else:
            data = dict()
            for i, thread_id in enumerate(thread_ids):
                data[f"{location.name.lower()}[{i}]"] = thread_id #type: ignore
            await self._payload_post("/ajax/mercury/move_thread.php", data)
        return True

    async def deleteThreads(self, thread_ids):
        """Delete threads.

        Args:
            thread_ids: Thread IDs to delete. See :ref:`intro_threads`

        Returns:
            True

        Raises:
            FBchatException: If request failed
        """
        thread_ids = require_list(thread_ids)

        data_unpin = dict()
        data_delete = dict()
        for i, thread_id in enumerate(thread_ids):
            data_unpin["ids[{}]".format(thread_id)] = "false"
            data_delete["ids[{}]".format(i)] = thread_id
        j_unpin = await self._payload_post(
            "/ajax/mercury/change_pinned_status.php?dpr=1", data_unpin
        )
        j_delete = await self._payload_post(
            "/ajax/mercury/delete_thread.php?dpr=1", data_delete
        )
        return True

    async def markAsSpam(self, thread_id=None):
        """Mark a thread as spam, and delete it.

        Args:
            thread_id: User/Group ID to mark as spam. See :ref:`intro_threads`

        Returns:
            True

        Raises:
            FBchatException: If request failed
        """
        thread_id, thread_type = self._getThread(thread_id, None)
        await self._payload_post("/ajax/mercury/mark_spam.php?dpr=1", {"id": thread_id})
        return True

    ###### Parse Events ######
    """

    PARSE EVENTS HERE

    """

    async def _parseDelta(self, delta):
        def getThreadIdAndThreadType(msg_metadata):
            """Return a tuple consisting of thread ID and thread type."""
            id_thread = None
            type_thread = None
            if "threadFbId" in msg_metadata["threadKey"]:
                id_thread = str(msg_metadata["threadKey"]["threadFbId"])
                type_thread = ThreadType.GROUP
            elif "otherUserFbId" in msg_metadata["threadKey"]:
                id_thread = str(msg_metadata["threadKey"]["otherUserFbId"])
                type_thread = ThreadType.USER
            return id_thread, type_thread

        delta_type = delta.get("type")
        delta_class = delta.get("class")
        metadata = delta.get("messageMetadata")
        mid = ""
        author_id = ""
        ts = 0
        if metadata: 
            mid = metadata["messageId"]
            author_id = str(metadata["actorFbId"])
            ts = int(metadata.get("timestamp"))


        if "addedParticipants" in delta:
            added_ids = [str(x["userFbId"]) for x in delta["addedParticipants"]]
            thread_id = str(metadata["threadKey"]["threadFbId"])
            await self.onPeopleAdded(
                mid=mid,
                added_ids=added_ids,
                author_id=author_id,
                thread_id=thread_id,
                ts=ts,
                msg=delta,
            )

        # Left/removed participants
        elif "leftParticipantFbId" in delta:
            removed_id = str(delta["leftParticipantFbId"])
            thread_id = str(metadata["threadKey"]["threadFbId"])
            await self.onPersonRemoved(
                mid=mid,
                removed_id=removed_id,
                author_id=author_id,
                thread_id=thread_id,
                ts=ts,
                msg=delta,
            )

        # Color change
        elif delta_type == "change_thread_theme":
            new_color = ThreadColor._from_graphql(delta["untypedData"]["theme_color"])
            thread_id, thread_type = getThreadIdAndThreadType(metadata)
            await self.onColorChange(
                mid=mid,
                author_id=author_id,
                new_color=new_color,
                thread_id=thread_id,
                thread_type=thread_type, #type: ignore
                ts=ts,
                metadata=metadata,
                msg=delta,
            )

        elif delta_class == "MarkFolderSeen":
            locations = [ThreadLocation(folder.lstrip("FOLDER_")) for folder in delta["folders"]]
            await self._onSeen(locations=locations, ts=delta["timestamp"], msg=delta)

        # Emoji change
        elif delta_type == "change_thread_icon":
            new_emoji = delta["untypedData"]["thread_icon"]
            thread_id, thread_type = getThreadIdAndThreadType(metadata)
            await self.onEmojiChange(
                mid=mid,
                author_id=author_id,
                new_emoji=new_emoji,
                thread_id=thread_id,
                thread_type=thread_type, #type: ignore
                ts=ts,
                metadata=metadata,
                msg=delta,
            )

        # Thread title change
        elif delta_class == "ThreadName":
            new_title = delta["name"]
            thread_id, thread_type = getThreadIdAndThreadType(metadata)
            await self.onTitleChange(
                mid=mid,
                author_id=author_id,
                new_title=new_title,
                thread_id=thread_id,
                thread_type=thread_type, #type: ignore
                ts=ts,
                metadata=metadata,
                msg=delta,
            )

        # Forced fetch
        elif delta_class == "ForcedFetch":
            print('class forced fetch')
            mid = delta.get("messageId")
            if mid is None:
                if delta["threadKey"] is not None:
                    # Looks like the whole delta is metadata in this case
                    thread_id, thread_type = getThreadIdAndThreadType(delta)
                    await self.onPendingMessage(
                        thread_id=thread_id,
                        thread_type=thread_type,
                        metadata=delta,
                        msg=delta,
                    )
            else:
                thread_id = str(delta["threadKey"]["threadFbId"])
                fetch_info = await self._forcedFetch(thread_id, mid)
                fetch_data = fetch_info["message"]
                author_id = fetch_data["message_sender"]["id"]
                ts = fetch_data["timestamp_precise"]
                if fetch_data.get("__typename") == "ThreadImageMessage":
                    # Thread image change
                    image_metadata = fetch_data.get("image_with_metadata")
                    image_id = (
                        int(image_metadata["legacy_attachment_id"])
                        if image_metadata
                        else None
                    )
                    await self.onImageChange(
                        mid=mid,
                        author_id=author_id,
                        new_image=image_id,
                        thread_id=thread_id,
                        thread_type=ThreadType.GROUP,
                        ts=ts,
                        msg=delta,
                    )

        # Nickname change
        elif delta_type == "change_thread_nickname":
            changed_for = str(delta["untypedData"]["participant_id"])
            new_nickname = delta["untypedData"]["nickname"]
            thread_id, thread_type = getThreadIdAndThreadType(metadata)
            await self.onNicknameChange(
                mid=mid,
                author_id=author_id,
                changed_for=changed_for,
                new_nickname=new_nickname,
                thread_id=thread_id,
                thread_type=thread_type, #type: ignore
                ts=ts,
                metadata=metadata,
                msg=delta,
            )

        # Admin added or removed in a group thread
        elif delta_type == "change_thread_admins":
            thread_id, thread_type = getThreadIdAndThreadType(metadata)
            target_id = delta["untypedData"]["TARGET_ID"]
            admin_event = delta["untypedData"]["ADMIN_EVENT"]
            if admin_event == "add_admin":
                await self.onAdminAdded(
                    mid=mid,
                    added_id=target_id,
                    author_id=author_id,
                    thread_id=thread_id,
                    thread_type=thread_type, #type: ignore
                    ts=ts,
                    msg=delta,
                )
            elif admin_event == "remove_admin":
                await self.onAdminRemoved(
                    mid=mid,
                    removed_id=target_id,
                    author_id=author_id,
                    thread_id=thread_id,
                    thread_type=thread_type, #type: ignore
                    ts=ts,
                    msg=delta,
                )

        # Group approval mode change
        elif delta_type == "change_thread_approval_mode":
            thread_id, thread_type = getThreadIdAndThreadType(metadata)
            approval_mode = bool(int(delta["untypedData"]["APPROVAL_MODE"]))
            await self.onApprovalModeChange(
                mid=mid,
                approval_mode=approval_mode,
                author_id=author_id,
                thread_id=thread_id,
                thread_type=thread_type, #type: ignore
                ts=ts,
                msg=delta,
            )

        # Message delivered
        elif delta_class == "DeliveryReceipt":
            message_ids = delta["messageIds"]
            delivered_for = str(
                delta.get("actorFbId") or delta["threadKey"]["otherUserFbId"]
            )
            ts = int(delta["deliveredWatermarkTimestampMs"])
            thread_id, thread_type = getThreadIdAndThreadType(delta)
            await self.onMessageDelivered(
                msg_ids=message_ids,
                delivered_for=delivered_for,
                thread_id=thread_id,
                thread_type=thread_type, #type: ignore
                ts=ts,
                metadata=metadata,
                msg=delta,
            )

        # Message seen
        elif delta_class == "ReadReceipt":
            seen_by = str(delta.get("actorFbId") or delta["threadKey"]["otherUserFbId"])
            seen_ts = int(delta["actionTimestampMs"])
            delivered_ts = int(delta["watermarkTimestampMs"])
            thread_id, thread_type = getThreadIdAndThreadType(delta)
            await self.onMessageSeen(
                seen_by=seen_by,
                thread_id=thread_id,
                thread_type=thread_type, #type: ignore
                seen_ts=seen_ts,
                ts=delivered_ts,
                metadata=metadata,
                msg=delta,
            )

        # Messages marked as seen
        elif delta_class == "MarkRead":
            seen_ts = int(
                delta.get("actionTimestampMs") or delta.get("actionTimestamp")
            )
            delivered_ts = int(
                delta.get("watermarkTimestampMs") or delta.get("watermarkTimestamp")
            )

            threads = []
            if "folders" not in delta:
                threads = [
                    getThreadIdAndThreadType({"threadKey": thr})
                    for thr in delta.get("threadKeys")
                ]

            # thread_id, thread_type = getThreadIdAndThreadType(delta)
            await self.onMarkedSeen(
                threads=threads,
                seen_ts=seen_ts,
                ts=delivered_ts,
                metadata=delta,
                msg=delta,
            )
        elif delta_class == "ClientPayload":
            payload = json.loads("".join(chr(z) for z in delta["payload"]))
            ts = now_time()  # Hack
            for d in payload.get("deltas", []):

                # Message reaction
                if d.get("deltaMessageReaction"):
                    i = d["deltaMessageReaction"]
                    thread_id, thread_type = getThreadIdAndThreadType(i)
                    mid = i["messageId"]
                    author_id = str(i["userId"])
                    reaction = (
                        MessageReaction(i["reaction"]) if i.get("reaction") else None
                    )
                    add_reaction = not bool(i["action"])
                    if add_reaction:
                        await self.onReactionAdded(
                            mid=mid,
                            reaction=reaction,
                            author_id=author_id,
                            thread_id=thread_id,
                            thread_type=thread_type,
                            ts=ts,
                            msg=delta,
                        )
                    else:
                        await self.onReactionRemoved(
                            mid=mid,
                            author_id=author_id,
                            thread_id=thread_id,
                            thread_type=thread_type,
                            ts=ts,
                            msg=delta,
                        )

                # Viewer status change
                elif d.get("deltaChangeViewerStatus"):
                    i = d["deltaChangeViewerStatus"]
                    thread_id, thread_type = getThreadIdAndThreadType(i)
                    author_id = str(i["actorFbid"])
                    reason = i["reason"]
                    can_reply = i["canViewerReply"]
                    if reason == 2:
                        if can_reply:
                            await self.onUnblock(
                                author_id=author_id,
                                thread_id=thread_id,
                                thread_type=thread_type,
                                ts=ts,
                                msg=delta,
                            )
                        else:
                            await self.onBlock(
                                author_id=author_id,
                                thread_id=thread_id,
                                thread_type=thread_type,
                                ts=ts,
                                msg=delta,
                            )

                # Live location info
                elif d.get("liveLocationData"):
                    i = d["liveLocationData"]
                    thread_id, thread_type = getThreadIdAndThreadType(i)
                    for l in i["messageLiveLocations"]:
                        mid = l["messageId"]
                        author_id = str(l["senderId"])
                        location = LiveLocationAttachment._from_pull(l)
                        await self.onLiveLocation(
                            mid=mid,
                            location=location,
                            author_id=author_id,
                            thread_id=thread_id,
                            thread_type=thread_type,
                            ts=ts,
                            msg=delta,
                        )

                # Message deletion
                elif d.get("deltaRecallMessageData"):
                    i = d["deltaRecallMessageData"]
                    thread_id, thread_type = getThreadIdAndThreadType(i)
                    mid = i["messageID"]
                    ts = i["deletionTimestamp"]
                    author_id = str(i["senderID"])
                    await self.onMessageUnsent(
                        mid=mid,
                        author_id=author_id,
                        thread_id=thread_id,
                        thread_type=thread_type,
                        ts=ts,
                        msg=delta,
                    )
                elif d.get("deltaMessageReply"):
                    i = d["deltaMessageReply"]
                    metadata = i["message"]["messageMetadata"]
                    thread_id, thread_type = getThreadIdAndThreadType(metadata)
                    message = Message._from_reply(i["message"], self, thread_id, thread_type)
                    message.replied_to = Message._from_reply(i["repliedToMessage"], self, thread_id, thread_type)
                    message.reply_to_id = message.replied_to.uid
                    await self.onReply(
                        mid=message.uid,
                        author_id=message.author,
                        message=message.text, #type: ignore
                        message_object=message,
                        thread_id=thread_id,
                        thread_type=thread_type, #type: ignore
                        ts=message.timestamp,
                        metadata=metadata,
                        msg=delta,
                    )
            # New message
        elif delta.get("class") == "NewMessage" and metadata:
            thread_id, thread_type = getThreadIdAndThreadType(metadata)
            await self.onMessage(
                mid=mid,
                author_id=author_id,
                message=delta.get("body", ""),
                message_object=Message._from_pull(
                    delta,
                    mid=mid,
                    tags=metadata.get("tags"),
                    author=author_id,
                    timestamp=ts,
                    client=self,
                    thread_id=thread_id,
                    thread_type=thread_type
                ),
                thread_id=thread_id,
                thread_type=thread_type, #type: ignore
                ts=ts,
                metadata=metadata,
                msg=delta,
            )



        # Unknown message type

    async def _parse_payload(self, topic, m):
        # Things that directly change chat
        if topic == "/t_ms" and self._mqtt:
            if "syncToken" in m and "firstDeltaSeqId" in m:
                self._mqtt._sync_token = m["syncToken"]
                self._mqtt._sequence_id = m["firstDeltaSeqId"]
                return
            if "lastIssuedSeqId" in m:
                self._mqtt._sequence_id = m["lastIssuedSeqId"]

            if "deltas" not in m:
                return
            for delta in m["deltas"]:
                await self._parseDelta(delta)
        elif topic == "/t_ms":
            if "deltas" not in m:
                return
            for delta in m["deltas"]:
                await self._parseDelta(delta)

        elif topic == "inbox":
            await self.onInbox(
                unseen=m["unseen"],
                unread=m["unread"],
                recent_unread=m["recent_unread"],
                msg=m,
            )

        # Chat timestamp / Buddylist overlay
        elif topic == "/orca_presence":
            if m["list_type"] == "full":
                self._buddylist = {}  # Refresh internal list

            statuses = dict()
            for data in m["list"]:
                user_id = str(data["u"])
                statuses[user_id] = ActiveStatus._from_orca_presence(data)
                self._buddylist[user_id] = statuses[user_id]

            # TODO: Which one should we call?

        # Unknown message type

    async def _parse_message(self, topic, data):
        try:
            await self._parse_payload(topic, data)
        except Exception as e:
            print(e)

    async def startListening(self):
        """Start listening from an external event loop.
        
        Raises:
            FBchatException: If request failed
        """
        if not self._mqtt:
            self._mqtt = await Mqtt.connect(
                state=self._state,
                chat_on=self._markAlive,
                foreground=True,
            )
            # Backwards compatibility
            await self.onQprimer(ts=now_time(), msg=None)
        self._listening = True


    async def stopListening(self):
        """Stop the listening loop."""
        self._listening = False
        await self._state._session.close()
        if not self._mqtt:
            return
        await self._mqtt.disconnect()
        # TODO: Preserve the _mqtt object
        # Currently, there's some issues when disconnecting
        self._mqtt = None


    async def listen(self, markAlive=True):
        """Listens to all kinds of events for now only messages and Messenger Group events are listened. For more wait for update"""
        if markAlive is not None:
            self.setActiveStatus(markAlive)
        if self._markAlive and self._mqtt:
                await self._mqtt.set_chat_on(self._markAlive)
                await self._mqtt.set_foreground(True)

        await self.startListening()
        await self.onListening()

        if not self._mqtt:
            raise RuntimeError("Mqtt instance is None. It shouldn't be None. please initialise Mqtt class first")

        while self._listening:

            async for messages in self._mqtt._mqttClient.messages:
                try:
                    topic = messages.topic.value
                    message = self._do_parse_json(messages.payload.decode("utf-8")) #type: ignore
                    await self._parse_message(topic, message)
                except Exception as e:
                    #raise RuntimeError
                    print("Got errors While listening: ", e)


    def _do_parse_json(self, data):
        try:
            return json.loads(data)
        except Exception as e:
            print("got errors while loading json: ", e)



    def setActiveStatus(self, markAlive):
        """ **Deprecated**
        Change active status while listening.

        Args:
            markAlive (bool): Whether to show if client is active
        """
        self._markAlive = markAlive

    """
    EVENTS
    """
    async def onListening(self):
        """Called when the client is listening."""

    async def onListenError(self, exception=None):
        """Called when an error was encountered while listening.

        Args:
            exception: The exception that was encountered

        Returns:
            Whether the loop should keep running
        """
        return True

    async def _onSeen(self, locations=None, ts=None, msg=None):
        """
        Todo:
            Document this, and make it public

        Args:
            locations: ---
            ts: A timestamp of the action
            msg: A full set of the data received
        """

    async def onInbox(self, unseen=None, unread=None, recent_unread=None, msg=None):
        """
        Called when some sends message requests
        """

    async def onMessage(
        self,
        mid: str,
        author_id: str,
        message: str,
        message_object: Message,
        thread_id = None,
        thread_type=ThreadType.USER,
        ts=None,
        metadata=None,
        msg=None,
    ):
        """Called when received a new message in messenger. 
        Above Arguments are received.

        Args:
            mid (str): message ID.
            author_id (str): message sender UID.
            message (str): The text message.
            message_object (Message): A Message object with full message data.
            thread_id (str): The thread message was sent from.
            thread_type (ThreadType): The type of the thread (e.g. User, Group)
            ts (int): timestamp of the message
            metadata (Dict): Full data of the received message
            msg : Full messagw
        """
    async def onReply(
        self,
        mid: str,
        author_id: str,
        message: str,
        message_object: Message,
        thread_id = None,
        thread_type=ThreadType.USER,
        ts=None,
        metadata=None,
        msg=None,
    ):
        """Called when received a new reply message in messenger 

        Args:
            mid (str): message ID.
            author_id (str): message sender UID.
            message (str): The text message.
            message_object (Message): A Message object with full message data.
            thread_id (str): The thread message was sent from.
            thread_type (ThreadType): The type of the thread (e.g. User, Group)
            ts (int): timestamp of the message
            metadata (Dict): Full data of the received message
            msg : Full messagw
        """
        pass

    async def onPendingMessage(
        self, thread_id=None, thread_type=None, metadata=None, msg=None
    ):
        """Called when the client is listening, and somebody that isn't
         connected with you on either Facebook or Messenger sends a message.
         After that, you need to use fetchThreadList to actually read the message.

         Args:
            thread_id: Thread ID that the message was sent to. See :ref:`intro_threads`
            thread_type (ThreadType): Type of thread that the message was sent to. See :ref:`intro_threads`
            metadata: Extra metadata about the message
            msg: A full set of the data received
        """
    async def onColorChange(
        self,
        mid=None,
        author_id=None,
        new_color=None,
        thread_id=None,
        thread_type=ThreadType.USER,
        ts=None,
        metadata=None,
        msg=None,
    ):
        """Called when the client is listening, and somebody changes a thread's color.

        Args:
            mid: The action ID
            author_id: The ID of the person who changed the color
            new_color (ThreadColor): The new color
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            thread_type (ThreadType): Type of thread that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            metadata: Extra metadata about the action
            msg: A full set of the data received
        """
    async def onEmojiChange(
        self,
        mid=None,
        author_id=None,
        new_emoji=None,
        thread_id=None,
        thread_type=ThreadType.USER,
        ts=None,
        metadata=None,
        msg=None,
    ):
        """Called when the client is listening, and somebody changes a thread's emoji.

        Args:
            mid: The action ID
            author_id: The ID of the person who changed the emoji
            new_emoji: The new emoji
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            thread_type (ThreadType): Type of thread that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            metadata: Extra metadata about the action
            msg: A full set of the data received
        """
    async def onTitleChange(
        self,
        mid=None,
        author_id=None,
        new_title=None,
        thread_id=None,
        thread_type=ThreadType.USER,
        ts=None,
        metadata=None,
        msg=None,
    ):
        """Called when the client is listening, and somebody changes a thread's title.

        Args:
            mid: The action ID
            author_id: The ID of the person who changed the title
            new_title: The new title
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            thread_type (ThreadType): Type of thread that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            metadata: Extra metadata about the action
            msg: A full set of the data received
        """
    async def onImageChange(
        self,
        mid=None,
        author_id=None,
        new_image=None,
        thread_id=None,
        thread_type=ThreadType.GROUP,
        ts=None,
        msg=None,
    ):
        """Called when the client is listening, and somebody changes a thread's image.

        Args:
            mid: The action ID
            author_id: The ID of the person who changed the image
            new_image: The ID of the new image
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            thread_type (ThreadType): Type of thread that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            msg: A full set of the data received
        """
    async def onNicknameChange(
        self,
        mid=None,
        author_id=None,
        changed_for=None,
        new_nickname=None,
        thread_id=None,
        thread_type=ThreadType.USER,
        ts=None,
        metadata=None,
        msg=None,
    ):
        """Called when the client is listening, and somebody changes a nickname.

        Args:
            mid: The action ID
            author_id: The ID of the person who changed the nickname
            changed_for: The ID of the person whom got their nickname changed
            new_nickname: The new nickname
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            thread_type (ThreadType): Type of thread that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            metadata: Extra metadata about the action
            msg: A full set of the data received
        """
    async def onAdminAdded(
        self,
        mid: str,
        added_id: str,
        author_id: str,
        thread_id=None,
        thread_type=ThreadType.GROUP,
        ts=None,
        msg=None,
    ):
        """Called when the client is listening, and somebody adds an admin to a group.

        Args:
            mid: The action ID
            added_id: The ID of the admin who got added
            author_id: The ID of the person who added the admins
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            msg: A full set of the data received
        """

    async def onAdminRemoved(
        self,
        mid=None,
        removed_id=None,
        author_id=None,
        thread_id=None,
        thread_type=ThreadType.GROUP,
        ts=None,
        msg=None,
    ):
        """Called when the client is listening, and somebody is removed as an admin in a group.

        Args:
            mid: The action ID
            removed_id: The ID of the admin who got removed
            author_id: The ID of the person who removed the admins
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            msg: A full set of the data received
        """

    async def onApprovalModeChange(
        self,
        mid=None,
        approval_mode=None,
        author_id=None,
        thread_id=None,
        thread_type=ThreadType.GROUP,
        ts=None,
        msg=None,
    ):
        """Called when the client is listening, and somebody changes approval mode in a group.

        Args:
            mid: The action ID
            approval_mode: True if approval mode is activated
            author_id: The ID of the person who changed approval mode
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            msg: A full set of the data received
        """

    async def onMessageSeen(
        self,
        seen_by=None,
        thread_id=None,
        thread_type=ThreadType.USER,
        seen_ts=None,
        ts=None,
        metadata=None,
        msg=None,
    ):
        """Called when the client is listening, and somebody marks a message as seen.

        Args:
            seen_by: The ID of the person who marked the message as seen
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            thread_type (ThreadType): Type of thread that the action was sent to. See :ref:`intro_threads`
            seen_ts: A timestamp of when the person saw the message
            ts: A timestamp of the action
            metadata: Extra metadata about the action
            msg: A full set of the data received
        """

    async def onMessageDelivered(
        self,
        msg_ids=None,
        delivered_for=None,
        thread_id=None,
        thread_type=ThreadType.USER,
        ts=None,
        metadata=None,
        msg=None,
    ):
        """Called when the client is listening, and somebody marks messages as delivered.

        Args:
            msg_ids: The messages that are marked as delivered
            delivered_for: The person that marked the messages as delivered
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            thread_type (ThreadType): Type of thread that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            metadata: Extra metadata about the action
            msg: A full set of the data received
        """

    async def onMarkedSeen(
        self, threads=None, seen_ts=None, ts=None, metadata=None, msg=None
    ):
        """Called when the client is listening, and the client has successfully marked threads as seen.

        Args:
            threads: The threads that were marked
            author_id: The ID of the person who changed the emoji
            seen_ts: A timestamp of when the threads were seen
            ts: A timestamp of the action
            metadata: Extra metadata about the action
            msg: A full set of the data received
        """

    async def onMessageUnsent(
        self,
        mid=None,
        author_id=None,
        thread_id=None,
        thread_type=None,
        ts=None,
        msg=None,
    ):
        """Called when the client is listening, and someone unsends (deletes for everyone) a message.

        Args:
            mid: ID of the unsent message
            author_id: The ID of the person who unsent the message
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            thread_type (ThreadType): Type of thread that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            msg: A full set of the data received
        """

    async def onReactionAdded(
        self,
        mid: str,
        reaction: MessageReaction,
        author_id: str,
        thread_id: str | None,
        thread_type=None,
        ts=None,
        msg=None,
    ):
        """Called when the client is listening, and somebody reacts to a message.

        Args:
            mid: Message ID, that user reacted to
            reaction (MessageReaction): Reaction
            author_id: The ID of the person who reacted to the message
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            thread_type (ThreadType): Type of thread that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            msg: A full set of the data received
        """

    async def onReactionRemoved(
        self,
        mid: str,
        author_id: str,
        thread_id: None | str,
        thread_type=None,
        ts=None,
        msg=None,
    ):
        """Called when the client is listening, and somebody removes reaction from a message.

        Args:
            mid: Message ID, that user reacted to
            author_id: The ID of the person who removed reaction
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            thread_type (ThreadType): Type of thread that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            msg: A full set of the data received
        """

    async def onBlock(
        self, author_id=None, thread_id=None, thread_type=None, ts=None, msg=None
    ):
        """Called when the client is listening, and somebody blocks client.

        Args:
            author_id: The ID of the person who blocked
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            thread_type (ThreadType): Type of thread that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            msg: A full set of the data received
        """

    async def onUnblock(
        self, author_id=None, thread_id=None, thread_type=None, ts=None, msg=None
    ):
        """Called when the client is listening, and somebody blocks client.

        Args:
            author_id: The ID of the person who unblocked
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            thread_type (ThreadType): Type of thread that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            msg: A full set of the data received
        """

    async def onLiveLocation(
        self,
        mid=None,
        location=None,
        author_id=None,
        thread_id=None,
        thread_type=None,
        ts=None,
        msg=None,
    ):
        """Called when the client is listening and somebody sends live location info.

        Args:
            mid: The action ID
            location (LiveLocationAttachment): Sent location info
            author_id: The ID of the person who sent location info
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            thread_type (ThreadType): Type of thread that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            msg: A full set of the data received
        """

    async def onPeopleAdded(
        self,
        mid=None,
        added_ids=None,
        author_id=None,
        thread_id=None,
        ts=None,
        msg=None,
    ):
        """Called when the client is listening, and somebody adds people to a group thread.

        Args:
            mid: The action ID
            added_ids: The IDs of the people who got added
            author_id: The ID of the person who added the people
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            msg: A full set of the data received
        """

    async def onPersonRemoved(
        self,
        mid=None,
        removed_id=None,
        author_id=None,
        thread_id=None,
        ts=None,
        msg=None,
    ):
        """Called when the client is listening, and somebody removes a person from a group thread.

        Args:
            mid: The action ID
            removed_id: The ID of the person who got removed
            author_id: The ID of the person who removed the person
            thread_id: Thread ID that the action was sent to. See :ref:`intro_threads`
            ts: A timestamp of the action
            msg: A full set of the data received
        """

    async def onFriendRequest(self, from_id=None, msg=None):
        """Called when the client is listening, and somebody sends a friend request.

        Args:
            from_id: The ID of the person that sent the request
            msg: A full set of the data received
        """

    async def onQprimer(self, ts=None, msg=None):
        """Called when the client just started listening.

        Args:
            ts: A timestamp of the action
            msg: A full set of the data received
        """
        pass
