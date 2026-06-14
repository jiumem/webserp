"""Engine registry."""

from .base import Engine, Result
from .google import Google
from .duckduckgo import DuckDuckGo
from .brave import Brave
from .yahoo import Yahoo
from .mojeek import Mojeek
from .startpage import Startpage
from .presearch import Presearch
from .bing_cn import BingCn
from .baidu import Baidu
from .sogou import Sogou
from .sogou_weixin import SogouWeixin
from .sogou_zhihu import SogouZhihu

ALL_ENGINES: dict[str, Engine] = {
    "google": Google(),
    "duckduckgo": DuckDuckGo(),
    "brave": Brave(),
    "yahoo": Yahoo(),
    "mojeek": Mojeek(),
    "startpage": Startpage(),
    "presearch": Presearch(),
    "bing_cn": BingCn(),
    "baidu": Baidu(),
    "sogou": Sogou(),
    "sogou_weixin": SogouWeixin(),
    "sogou_zhihu": SogouZhihu(),
}

DEFAULT_ENGINES: dict[str, Engine] = {
    name: engine
    for name, engine in ALL_ENGINES.items()
    if name != "sogou_zhihu"
}

__all__ = ["ALL_ENGINES", "DEFAULT_ENGINES", "Engine", "Result"]
