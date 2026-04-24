from abc import ABC, abstractmethod

from app.domains.study.domain.entity.study_video_input import StudyVideoInput
from app.domains.study.domain.entity.video_learning import VideoLearning


class VideoLearningLlmPort(ABC):
    @abstractmethod
    async def learn(self, video: StudyVideoInput) -> VideoLearning:
        pass
