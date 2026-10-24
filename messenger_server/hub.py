"""Раздача событий подключённым клиентам.

У каждого открытого потока Subscribe своя очередь. Отправитель кладёт событие
в очереди получателя, и поток сразу отдаёт его клиенту — без опроса раз в 50 мс,
как было в старой версии, поэтому простаивающий сервер не тратит процессор.
"""
import asyncio
from collections import defaultdict

from proto import messenger_pb2 as pb

QUEUE_SIZE = 1000  # если клиент не успевает читать, лишнее отбрасываем: он догонит через History


class Hub:
    def __init__(self) -> None:
        self._queues: dict[int, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, user_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._queues[user_id].add(queue)
        return queue

    def unsubscribe(self, user_id: int, queue: asyncio.Queue) -> None:
        self._queues[user_id].discard(queue)
        if not self._queues[user_id]:
            del self._queues[user_id]

    def publish(self, user_id: int, event: pb.Event) -> None:
        for queue in list(self._queues.get(user_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def online(self, user_id: int) -> bool:
        return bool(self._queues.get(user_id))
