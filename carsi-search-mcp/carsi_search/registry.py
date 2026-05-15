"""
Database adapter registry — add new databases here.
"""

import asyncio
from pathlib import Path

DB_REGISTRY = {
    "zhizhen": {
        "name": "zhizhen",
        "label": "智真/超星发现 (Zhizhen)",
        "sp_url": (
            "https://fsso.zhizhen.com/Shibboleth.sso/Login"
            "?entityID={entity_id_raw}"
            "&target=https://fsso.zhizhen.com/carsi/secure"
        ),
        "home_url": "https://ss.zhizhen.com/",
        "cookie_accept": [],
        "target_url_pattern": "**/zhizhen.com/**",
        "adapter": "carsi_search.databases.zhizhen:ZhizhenAdapter",
    },

    "ieee": {
        "name": "ieee",
        "label": "IEEE Xplore",
        "sp_url": (
            "https://ieeexplore.ieee.org/servlet/wayf.jsp"
            "?entityId={entity_id_raw}"
            "&url=https%3A%2F%2Fieeexplore.ieee.org%2FXplore%2Fhome.jsp"
        ),
        "home_url": "https://ieeexplore.ieee.org/Xplore/home.jsp",
        "cookie_accept": [
            'button:has-text("全部接受")',
            'button:has-text("Accept All")',
        ],
        "target_url_pattern": "**/ieeexplore.ieee.org/Xplore/**",
        "adapter": "carsi_search.databases.ieee:IeeeAdapter",
    },
}


def get_db(name: str) -> dict | None:
    return DB_REGISTRY.get(name)


def list_dbs() -> list[str]:
    return list(DB_REGISTRY.keys())


def _import_adapter(adapter_path: str):
    import importlib
    module_path, class_name = adapter_path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


async def get_adapter(name: str, page):
    db = get_db(name)
    if not db:
        raise ValueError(f"Unknown database: {name}. Available: {list_dbs()}")
    cls = _import_adapter(db["adapter"])
    return cls(page)
