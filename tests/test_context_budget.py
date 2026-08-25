from pathlib import Path

from mewcode.context.budget import TokenEstimator
from mewcode.context.controller import ContextController, _retained_start
from mewcode.llm import ImageContent, Message
from mewcode.session.archive import ArchiveWriter


def test_estimator_uses_usage_anchor_and_reserves() -> None:
    estimator = TokenEstimator()
    assert estimator.estimate(40) == 10
    estimator.record_usage(100, 400)
    assert estimator.estimate(440) == 110
    assert estimator.exceeds(440, 13_100)
    assert not estimator.exceeds(440, 13_100, manual=True)


def test_context_request_budget_counts_image_tokens_not_base64(tmp_path: Path) -> None:
    class ProviderStub:
        def redact(self, text: str) -> str:
            return text

    writer = ArchiveWriter(tmp_path / "session.jsonl")
    controller = ContextController(
        ProviderStub(),  # type: ignore[arg-type]
        writer,
        tmp_path / "cache",
        1_000_000,
    )
    message = Message(
        role="user",
        content="图",
        images=[ImageContent(media_type="image/png", data="x" * 100_000)],
    )

    assert controller.request_chars([message], "", []) == 1 + 1536
    writer.close()


def test_compaction_retains_image_during_three_followup_turns() -> None:
    image = ImageContent(media_type="image/png", data="eA==")
    messages = [Message("user", f"旧消息 {index}") for index in range(10)]
    image_index = len(messages)
    messages.append(Message("user", "看图", images=[image]))
    for index in range(3):
        messages.extend(
            [Message("assistant", "回答"), Message("user", f"追问 {index}")]
        )

    assert _retained_start(messages) <= image_index
