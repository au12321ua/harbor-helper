"""Local fake streaming endpoints with one real shell tool round trip, no upstream."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ProtocolServer(ThreadingHTTPServer):
    def __init__(self, address=("127.0.0.1", 0)):
        super().__init__(address, Handler)
        self.records = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def stream(self, events):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for name, value in events:
            text = value if isinstance(value, str) else json.dumps(value)
            self.wfile.write(((f"event: {name}\n" if name else "") + f"data: {text}\n\n").encode())
            self.wfile.flush()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert isinstance(self.server, ProtocolServer)
        self.server.records.append({"path": self.path, "headers": dict(self.headers), "body": body})
        # First request includes the instruction, later request has the actual
        # tool result. Do not confuse the tool arguments with its returned data.
        serialized = json.dumps(body)
        done = (
            '"role": "tool"' in serialized
            or '"function_call_output"' in serialized
            or '"tool_result"' in serialized
        )
        done = done or not body.get("tools")
        args = json.dumps(
            {"command": "printf WIRE_TOOL_OK", "description": "Verify local fake tool roundtrip"}
        )
        if self.path.endswith("/chat/completions"):
            base = {
                "id": "chat-fake",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": body["model"],
            }
            delta = (
                {"role": "assistant", "content": "WIRE_TEXT_OK"}
                if done
                else {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_fake",
                            "type": "function",
                            "function": {"name": "bash", "arguments": args},
                        }
                    ],
                }
            )
            self.stream(
                [
                    (
                        None,
                        {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                    ),
                    (
                        None,
                        {
                            **base,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {},
                                    "finish_reason": "stop" if done else "tool_calls",
                                }
                            ],
                            "usage": {
                                "prompt_tokens": 13,
                                "completion_tokens": 5,
                                "total_tokens": 18,
                            },
                        },
                    ),
                    (None, "[DONE]"),
                ]
            )
        elif self.path.endswith("/responses"):
            response = {
                "id": "resp_fake",
                "object": "response",
                "created_at": 1,
                "model": body["model"],
                "status": "in_progress",
                "output": [],
            }
            item = (
                {
                    "id": "msg_fake",
                    "type": "message",
                    "role": "assistant",
                    "status": "in_progress",
                    "content": [],
                }
                if done
                else {
                    "id": "fc_fake",
                    "type": "function_call",
                    "call_id": "call_fake",
                    "name": "bash",
                    "arguments": "",
                    "status": "in_progress",
                }
            )
            completed = {
                **item,
                "status": "completed",
                **(
                    {
                        "content": [
                            {"type": "output_text", "text": "WIRE_TEXT_OK", "annotations": []}
                        ]
                    }
                    if done
                    else {"arguments": args}
                ),
            }
            events = [
                (
                    "response.created",
                    {"type": "response.created", "sequence_number": 0, "response": response},
                ),
                (
                    "response.output_item.added",
                    {
                        "type": "response.output_item.added",
                        "sequence_number": 1,
                        "output_index": 0,
                        "item": item,
                    },
                ),
            ]
            if done:
                events.extend(
                    [
                        (
                            "response.content_part.added",
                            {
                                "type": "response.content_part.added",
                                "sequence_number": 2,
                                "item_id": item["id"],
                                "output_index": 0,
                                "content_index": 0,
                                "part": {"type": "output_text", "text": "", "annotations": []},
                            },
                        ),
                        (
                            "response.output_text.delta",
                            {
                                "type": "response.output_text.delta",
                                "sequence_number": 3,
                                "item_id": item["id"],
                                "output_index": 0,
                                "content_index": 0,
                                "delta": "WIRE_TEXT_OK",
                                "logprobs": [],
                            },
                        ),
                    ]
                )
            else:
                events.extend(
                    [
                        (
                            "response.function_call_arguments.delta",
                            {
                                "type": "response.function_call_arguments.delta",
                                "sequence_number": 2,
                                "item_id": item["id"],
                                "output_index": 0,
                                "delta": args,
                            },
                        ),
                        (
                            "response.function_call_arguments.done",
                            {
                                "type": "response.function_call_arguments.done",
                                "sequence_number": 3,
                                "item_id": item["id"],
                                "output_index": 0,
                                "arguments": args,
                            },
                        ),
                    ]
                )
            events.extend(
                [
                    (
                        "response.output_item.done",
                        {
                            "type": "response.output_item.done",
                            "sequence_number": 4,
                            "output_index": 0,
                            "item": completed,
                        },
                    ),
                    (
                        "response.completed",
                        {
                            "type": "response.completed",
                            "sequence_number": 5,
                            "response": {
                                **response,
                                "status": "completed",
                                "output": [completed],
                                "usage": {
                                    "input_tokens": 13,
                                    "output_tokens": 5,
                                    "total_tokens": 18,
                                    "input_tokens_details": {"cached_tokens": 0},
                                    "output_tokens_details": {"reasoning_tokens": 0},
                                },
                            },
                        },
                    ),
                ]
            )
            self.stream(events)
        elif self.path.endswith("/messages"):
            self.stream(
                [
                    (
                        "message_start",
                        {
                            "type": "message_start",
                            "message": {
                                "id": "msg_fake",
                                "type": "message",
                                "role": "assistant",
                                "model": body["model"],
                                "content": [],
                                "stop_reason": None,
                                "stop_sequence": None,
                                "usage": {"input_tokens": 13, "output_tokens": 0},
                            },
                        },
                    ),
                    (
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {"type": "text", "text": ""}
                            if done
                            else {
                                "type": "tool_use",
                                "id": "call_fake",
                                "name": "bash",
                                "input": {},
                            },
                        },
                    ),
                    (
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": "WIRE_TEXT_OK"}
                            if done
                            else {"type": "input_json_delta", "partial_json": args},
                        },
                    ),
                    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                    (
                        "message_delta",
                        {
                            "type": "message_delta",
                            "delta": {
                                "stop_reason": "end_turn" if done else "tool_use",
                                "stop_sequence": None,
                            },
                            "usage": {"output_tokens": 5},
                        },
                    ),
                    ("message_stop", {"type": "message_stop"}),
                ]
            )
        else:
            self.send_response(404)
            self.end_headers()
