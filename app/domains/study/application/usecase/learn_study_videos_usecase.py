import logging
from datetime import datetime, timedelta, timezone
from typing import List

from app.domains.study.application.port.out.study_note_reader_port import StudyNoteReaderPort
from app.domains.study.application.port.out.study_note_writer_port import StudyNoteWriterPort
from app.domains.study.application.port.out.transcript_fetch_port import TranscriptFetchPort
from app.domains.study.application.port.out.video_learning_llm_port import VideoLearningLlmPort
from app.domains.study.application.port.out.video_source_port import VideoSourcePort
from app.domains.study.application.request.learn_study_request import LearnStudyRequest
from app.domains.study.application.response.learn_study_response import (
    LearnStudyResponse,
    ProcessedVideoSummary,
)
from app.domains.study.domain.entity.study_video_input import StudyVideoInput
from app.domains.study.domain.entity.video_learning import VideoLearning
from app.domains.study.domain.value_object.learning_program_type import LearningProgramType

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 30


class LearnStudyVideosUseCase:
    def __init__(
        self,
        video_source_port: VideoSourcePort,
        transcript_port: TranscriptFetchPort,
        llm_port: VideoLearningLlmPort,
        note_reader_port: StudyNoteReaderPort,
        note_writer_port: StudyNoteWriterPort,
    ):
        self._video_source_port = video_source_port
        self._transcript_port = transcript_port
        self._llm_port = llm_port
        self._note_reader_port = note_reader_port
        self._note_writer_port = note_writer_port

    async def execute(self, request: LearnStudyRequest) -> LearnStudyResponse:
        print(f"[study.usecase] ▶ 시작 channels={request.channel_ids} max_per_channel={request.max_per_channel}")

        channel_ids = [cid for cid in request.channel_ids if cid]
        if not channel_ids:
            print("[study.usecase] ⚠ 채널 목록이 비어있음 — 조회 생략")
            logger.info("[study.learn] 채널 목록이 비어있어 영상 조회를 수행하지 않습니다.")
            return LearnStudyResponse(
                file_path="",
                processed_count=0,
                skipped_duplicate_count=0,
                total_candidates=0,
                processed_videos=[],
                message="채널 목록이 비어있어 처리하지 않았습니다.",
            )

        published_after = request.published_after or (
            datetime.now(timezone.utc) - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        )
        print(f"[study.usecase] Step1. 영상 조회 published_after={published_after.isoformat()}")

        raw_videos = await self._video_source_port.fetch_by_channels(
            channel_ids=channel_ids,
            published_after=published_after,
            max_per_channel=request.max_per_channel,
        )
        print(f"[study.usecase] Step1. 수집된 원시 영상 개수={len(raw_videos)}")

        if not raw_videos:
            print("[study.usecase] ⚠ 조회된 영상이 0건 — 종료")
            logger.info("[study.learn] 조회된 영상이 없습니다. channels=%s", channel_ids)
            return LearnStudyResponse(
                file_path="",
                processed_count=0,
                skipped_duplicate_count=0,
                total_candidates=0,
                processed_videos=[],
                message="조회된 영상이 없습니다.",
            )

        target_videos = self._filter_target_programs(raw_videos)
        target_videos.sort(key=lambda v: v.published_at, reverse=True)
        print(f"[study.usecase] Step2. 프로그램 필터 통과 = {len(target_videos)} / 원시 {len(raw_videos)}")

        existing_ids = await self._note_reader_port.existing_video_ids()
        print(f"[study.usecase] Step3. 기존 study.md 내 video_id 수 = {len(existing_ids)}")

        candidates: List[StudyVideoInput] = []
        duplicate_count = 0
        seen_ids: set[str] = set()
        for video in target_videos:
            if video.video_id in existing_ids or video.video_id in seen_ids:
                duplicate_count += 1
                continue
            seen_ids.add(video.video_id)
            candidates.append(video)
        print(
            f"[study.usecase] Step3. 중복 제외 후 학습 대상 = {len(candidates)} "
            f"(중복 skip={duplicate_count})"
        )

        learnings: List[VideoLearning] = []
        for idx, video in enumerate(candidates, start=1):
            print(
                f"[study.usecase] Step4. ({idx}/{len(candidates)}) 학습 시작 "
                f"video_id={video.video_id} title={video.title[:40]!r}"
            )
            try:
                video.transcript = await self._transcript_port.fetch(video.video_id)
                transcript_len = len(video.transcript) if video.transcript else 0
                print(f"[study.usecase]   └ 자막 길이 = {transcript_len}자")

                learning = await self._llm_port.learn(video)
                print(
                    f"[study.usecase]   └ LLM 학습 완료 program={learning.program_type.value} "
                    f"stocks={len(learning.stock_insights)}"
                )
                learnings.append(learning)
            except Exception as exc:
                print(f"[study.usecase]   └ ❌ 학습 실패 video_id={video.video_id}: {exc}")
                logger.exception("[study.learn] 영상 학습 실패 video_id=%s: %s", video.video_id, exc)
                continue

        file_path = ""
        if learnings:
            markdown = self._render_markdown(learnings)
            print(f"[study.usecase] Step5. Markdown 생성 길이 = {len(markdown)}자")
            file_path = await self._note_writer_port.append(markdown)
            print(f"[study.usecase] Step5. 파일 저장 완료 path={file_path}")
        else:
            print("[study.usecase] Step5. 저장할 학습 결과가 없어 파일 append 생략")

        print(
            f"[study.usecase] ■ 완료 processed={len(learnings)} "
            f"skipped_duplicate={duplicate_count} candidates={len(target_videos)} file={file_path or '(없음)'}"
        )
        logger.info(
            "[study.learn] 저장 완료 file=%s processed=%d skipped_duplicate=%d candidates=%d",
            file_path,
            len(learnings),
            duplicate_count,
            len(target_videos),
        )

        return LearnStudyResponse(
            file_path=file_path,
            processed_count=len(learnings),
            skipped_duplicate_count=duplicate_count,
            total_candidates=len(target_videos),
            processed_videos=[
                ProcessedVideoSummary(
                    video_id=learning.video_id,
                    title=learning.title,
                    program_type=learning.program_type.value,
                    stock_count=len(learning.stock_insights),
                )
                for learning in learnings
            ],
            message="학습 결과를 저장했습니다." if learnings else "신규 학습 대상 영상이 없습니다.",
        )

    @staticmethod
    def _filter_target_programs(videos: List[StudyVideoInput]) -> List[StudyVideoInput]:
        result: List[StudyVideoInput] = []
        for v in videos:
            program = LearningProgramType.classify(v.title, v.description)
            if LearningProgramType.is_target(program):
                result.append(v)
        return result

    @staticmethod
    def _render_markdown(learnings: List[VideoLearning]) -> str:
        blocks: List[str] = []
        for learning in learnings:
            block_lines: List[str] = []
            block_lines.append(f"## [학습프로그램] {learning.title}")
            block_lines.append("")
            block_lines.append(f"- video_id: `{learning.video_id}`")
            block_lines.append(f"- 채널: {learning.channel_name} ({learning.channel_id})")
            block_lines.append(f"- 프로그램: {learning.program_type.value}")
            block_lines.append(f"- 업로드일: {learning.published_at.strftime('%Y-%m-%d')}")
            block_lines.append(f"- 학습일시: {learning.collected_at.strftime('%Y-%m-%d %H:%M')}")
            block_lines.append("")
            block_lines.append("### 핵심 요약")
            block_lines.append(learning.summary.strip() or "(요약 없음)")
            block_lines.append("")

            if learning.stock_insights:
                block_lines.append("### 종목별 인사이트")
                for insight in learning.stock_insights:
                    block_lines.append(f"#### {insight.stock_name}")
                    block_lines.append(f"- 투자 관점: {insight.investment_view.value}")
                    if insight.key_claims:
                        block_lines.append("- 핵심 주장:")
                        for claim in insight.key_claims:
                            block_lines.append(f"  - {claim}")
                    if insight.evidences:
                        block_lines.append("- 근거:")
                        for evidence in insight.evidences:
                            block_lines.append(f"  - {evidence}")
                    block_lines.append("")
            blocks.append("\n".join(block_lines).rstrip())

        return "\n\n".join(blocks) + "\n"
