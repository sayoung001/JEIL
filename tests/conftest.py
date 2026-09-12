"""테스트 공통 설정. GUI 테스트는 화면 없이 돌린다."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
