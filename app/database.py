import os
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from app.config import settings

def utc_now():
    return datetime.now(timezone.utc)

class Predicate:
    def __init__(self, func):
        self.func = func

    def __call__(self, obj):
        try:
            return bool(self.func(obj))
        except Exception:
            return False

    def __and__(self, other):
        return Predicate(lambda obj: self(obj) and other(obj))

    def __or__(self, other):
        return Predicate(lambda obj: self(obj) or other(obj))

    def __invert__(self):
        return Predicate(lambda obj: not self(obj))

class OrderSpec:
    def __init__(self, field_name: str, is_desc: bool = False):
        self.field_name = field_name
        self.is_desc = is_desc

def desc(field_or_spec):
    if isinstance(field_or_spec, OrderSpec):
        field_or_spec.is_desc = True
        return field_or_spec
    if hasattr(field_or_spec, "name"):
        return OrderSpec(field_or_spec.name, is_desc=True)
    if isinstance(field_or_spec, str):
        return OrderSpec(field_or_spec, is_desc=True)
    return field_or_spec

def asc(field_or_spec):
    if isinstance(field_or_spec, OrderSpec):
        field_or_spec.is_desc = False
        return field_or_spec
    if hasattr(field_or_spec, "name"):
        return OrderSpec(field_or_spec.name, is_desc=False)
    if isinstance(field_or_spec, str):
        return OrderSpec(field_or_spec, is_desc=False)
    return field_or_spec

class Field:
    def __init__(self, name: str = "", default=None, default_factory=None, primary_key: bool = False):
        self.name = name
        self.default = default
        self.default_factory = default_factory
        self.primary_key = primary_key

    def __eq__(self, other):
        if other is None:
            return Predicate(lambda obj: getattr(obj, self.name, None) is None)
        return Predicate(lambda obj: getattr(obj, self.name, None) == other)

    def __ne__(self, other):
        if other is None:
            return Predicate(lambda obj: getattr(obj, self.name, None) is not None)
        return Predicate(lambda obj: getattr(obj, self.name, None) != other)

    def __gt__(self, other):
        return Predicate(lambda obj: (getattr(obj, self.name, None) or 0) > other)

    def __lt__(self, other):
        return Predicate(lambda obj: (getattr(obj, self.name, None) or 0) < other)

    def __ge__(self, other):
        return Predicate(lambda obj: (getattr(obj, self.name, None) or 0) >= other)

    def __le__(self, other):
        return Predicate(lambda obj: (getattr(obj, self.name, None) or 0) <= other)

    def ilike(self, pattern: str):
        clean = str(pattern).lower().replace("%", "")
        return Predicate(lambda obj: clean in str(getattr(obj, self.name, "") or "").lower())

    def like(self, pattern: str):
        clean = str(pattern).replace("%", "")
        return Predicate(lambda obj: clean in str(getattr(obj, self.name, "") or ""))

    def in_(self, collection):
        col_set = set(collection)
        return Predicate(lambda obj: getattr(obj, self.name, None) in col_set)

    def desc(self):
        return OrderSpec(self.name, is_desc=True)

    def asc(self):
        return OrderSpec(self.name, is_desc=False)

def Column(*args, **kwargs):
    default = kwargs.get("default")
    default_factory = None
    if callable(default):
        default_factory = default
        default = None
    primary_key = kwargs.get("primary_key", False)
    return Field(default=default, default_factory=default_factory, primary_key=primary_key)

class Integer: pass
class String:
    def __init__(self, *args, **kwargs): pass
class Boolean: pass
class DateTime: pass
class Text: pass
class Float: pass
class ForeignKey:
    def __init__(self, *args, **kwargs): pass

class Relationship:
    def __init__(self, target_model_name: str, back_populates: str = "", cascade: str = ""):
        self.target_model_name = target_model_name
        self.back_populates = back_populates

def relationship(*args, **kwargs):
    target = args[0] if args else kwargs.get("argument")
    return Relationship(target, back_populates=kwargs.get("back_populates", ""))

_REGISTERED_MODELS = {}

class ModelMeta(type):
    def __new__(mcs, name, bases, namespace):
        fields = {}
        for k, v in list(namespace.items()):
            if isinstance(v, Field):
                v.name = k
                fields[k] = v
        namespace["_fields"] = fields
        if "__tablename__" not in namespace:
            namespace["__tablename__"] = name.lower() + "s"
        cls = super().__new__(mcs, name, bases, namespace)
        _REGISTERED_MODELS[namespace["__tablename__"]] = cls
        return cls

class MetaDataDummy:
    def create_all(self, bind=None):
        get_json_db().load()

class BaseModel(metaclass=ModelMeta):
    metadata = MetaDataDummy()

    def __init__(self, **kwargs):
        for k, field in self._fields.items():
            if k in kwargs:
                setattr(self, k, kwargs[k])
            elif field.default_factory:
                setattr(self, k, field.default_factory())
            else:
                setattr(self, k, field.default)
        for k, v in kwargs.items():
            if k not in self._fields:
                setattr(self, k, v)

    def to_dict(self):
        d = {}
        for k in self._fields:
            val = getattr(self, k, None)
            if isinstance(val, datetime):
                d[k] = val.isoformat()
            else:
                d[k] = val
        return d

    @classmethod
    def from_dict(cls, data):
        obj = cls()
        for k, v in data.items():
            field = cls._fields.get(k)
            if v is not None and ('time' in k.lower() or 'at' in k.lower()):
                try:
                    setattr(obj, k, datetime.fromisoformat(str(v).replace('Z', '+00:00')))
                    continue
                except Exception:
                    pass
            setattr(obj, k, v)
        return obj

    def __repr__(self):
        pk = getattr(self, "id", getattr(self, "key", None))
        return f"<{self.__class__.__name__} id={pk}>"

Base = BaseModel

class JsonDatabase:
    def __init__(self, filepath=None):
        self.filepath = filepath or getattr(settings, "DATABASE_FILE", "films_over_web.json")
        self.lock = threading.RLock()
        self.collections = {
            "users": [],
            "drive_folders": [],
            "movies": [],
            "series": [],
            "episodes": [],
            "system_settings": [],
            "watch_progress": [],
            "tv_login_codes": []
        }
        self.load()

    def load(self):
        with self.lock:
            if not os.path.exists(self.filepath):
                # If sqlite exists, auto-migrate!
                sqlite_path = getattr(settings, "BASE_DIR", Path(".")) / "films_over_web.db"
                if os.path.exists(sqlite_path):
                    self._migrate_from_sqlite(sqlite_path)
                return

            try:
                mtime = os.path.getmtime(self.filepath)
                self._last_mtime = mtime
                with open(self.filepath, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                for table_name, rows in raw_data.items():
                    model_cls = _REGISTERED_MODELS.get(table_name)
                    if model_cls:
                        self.collections[table_name] = [
                            model_cls.from_dict(r) if isinstance(r, dict) else r for r in rows
                        ]
                    else:
                        self.collections[table_name] = list(rows)
            except Exception as e:
                print(f"[JSON_DB] Warning: failed to parse {self.filepath}: {e}")

    def _migrate_from_sqlite(self, sqlite_path):
        try:
            import sqlite3
            conn = sqlite3.connect(sqlite_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            raw_data = {}
            for table in ["users", "drive_folders", "movies", "system_settings", "watch_progress"]:
                try:
                    cur.execute(f"SELECT * FROM {table}")
                    raw_data[table] = [dict(r) for r in cur.fetchall()]
                except Exception:
                    raw_data[table] = []
            conn.close()

            for table_name, rows in raw_data.items():
                model_cls = _REGISTERED_MODELS.get(table_name)
                if model_cls:
                    self.collections[table_name] = [model_cls.from_dict(r) for r in rows]
                else:
                    self.collections[table_name] = list(rows)

            self.save()
            print(f"[JSON_DB] Automatically migrated SQLite database to {self.filepath} successfully!")
        except Exception as err:
            print(f"[JSON_DB] Migration from SQLite failed: {err}")

    def save(self):
        with self.lock:
            data = {}
            for table_name, objects in self.collections.items():
                data[table_name] = [obj.to_dict() if hasattr(obj, "to_dict") else obj for obj in objects]
            tmp_path = self.filepath + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            
            import time
            for attempt in range(5):
                try:
                    os.replace(tmp_path, self.filepath)
                    break
                except (PermissionError, OSError):
                    if attempt == 4:
                        try:
                            with open(self.filepath, "w", encoding="utf-8") as f:
                                json.dump(data, f, indent=2, default=str)
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)
                        except Exception:
                            pass
                    else:
                        time.sleep(0.05)
            try:
                self._last_mtime = os.path.getmtime(self.filepath)
            except Exception:
                pass

    def get_collection(self, model_cls):
        with self.lock:
            try:
                if os.path.exists(self.filepath):
                    mtime = os.path.getmtime(self.filepath)
                    if not hasattr(self, "_last_mtime") or mtime > self._last_mtime:
                        self.load()
            except Exception:
                pass
            table_name = getattr(model_cls, "__tablename__", model_cls.__name__.lower() + "s")
            if table_name not in self.collections:
                self.collections[table_name] = []
            col = self.collections[table_name]
            for i in range(len(col)):
                if isinstance(col[i], dict):
                    col[i] = model_cls.from_dict(col[i])
            return list(self.collections[table_name])

    def get_by_id(self, model_cls, pk_val):
        if pk_val is None:
            return None
        for obj in self.get_collection(model_cls):
            if getattr(obj, "id", None) == pk_val or getattr(obj, "key", None) == pk_val:
                return obj
        return None

    def add(self, obj):
        with self.lock:
            table_name = getattr(obj, "__tablename__", obj.__class__.__name__.lower() + "s")
            if table_name not in self.collections:
                self.collections[table_name] = []

            col = self.collections[table_name]
            # Primary key auto-generation if id is empty
            if hasattr(obj, "id") and not obj.id:
                max_id = max([getattr(x, "id", 0) or 0 for x in col], default=0)
                obj.id = max_id + 1
            if obj not in col:
                col.append(obj)

    def add_all(self, objs):
        for obj in objs:
            self.add(obj)

    def delete(self, obj):
        with self.lock:
            table_name = getattr(obj, "__tablename__", obj.__class__.__name__.lower() + "s")
            if table_name in self.collections:
                col = self.collections[table_name]
                if obj in col:
                    col.remove(obj)

            # Cascade deletions
            if table_name == "drive_folders":
                movie_col = self.collections.get("movies", [])
                self.collections["movies"] = [m for m in movie_col if getattr(m, "folder_id", None) != obj.id]
                ep_col = self.collections.get("episodes", [])
                self.collections["episodes"] = [e for e in ep_col if getattr(e, "folder_id", None) != obj.id]
            elif table_name == "users":
                wp_col = self.collections.get("watch_progress", [])
                self.collections["watch_progress"] = [p for p in wp_col if getattr(p, "user_id", None) != obj.id]
            elif table_name == "movies":
                wp_col = self.collections.get("watch_progress", [])
                self.collections["watch_progress"] = [p for p in wp_col if getattr(p, "movie_id", None) != obj.id]
            elif table_name == "series":
                ep_col = self.collections.get("episodes", [])
                self.collections["episodes"] = [e for e in ep_col if getattr(e, "series_id", None) != obj.id]
            elif table_name == "episodes":
                wp_col = self.collections.get("watch_progress", [])
                self.collections["watch_progress"] = [p for p in wp_col if getattr(p, "episode_id", None) != obj.id]

class JsonQuery:
    def __init__(self, db, model_cls, items=None):
        self.db = db
        self.model_cls = model_cls
        self.items = list(items if items is not None else db.get_collection(model_cls))

    def filter(self, *predicates):
        filtered = self.items
        for pred in predicates:
            if callable(pred):
                filtered = [item for item in filtered if pred(item)]
        return JsonQuery(self.db, self.model_cls, filtered)

    def order_by(self, *specs):
        sorted_items = list(self.items)
        for spec in reversed(specs):
            field_name = spec.field_name if isinstance(spec, OrderSpec) else getattr(spec, "name", str(spec))
            is_desc = spec.is_desc if isinstance(spec, OrderSpec) else False

            def sort_key(item):
                val = getattr(item, field_name, None)
                if val is None:
                    return (1, 0) if is_desc else (-1, 0)
                if isinstance(val, datetime):
                    if val.tzinfo is not None:
                        val = val.astimezone(timezone.utc).replace(tzinfo=None)
                    return (0, val.timestamp())
                return (0, val)

            sorted_items.sort(key=sort_key, reverse=is_desc)
        return JsonQuery(self.db, self.model_cls, sorted_items)

    def limit(self, n: int):
        return JsonQuery(self.db, self.model_cls, self.items[:n])

    def offset(self, n: int):
        return JsonQuery(self.db, self.model_cls, self.items[n:])

    def all(self):
        return list(self.items)

    def first(self):
        return self.items[0] if self.items else None

    def count(self):
        return len(self.items)

class JsonSession:
    def __init__(self, db=None):
        self.db = db or get_json_db()

    def query(self, model_cls):
        return JsonQuery(self.db, model_cls)

    def add(self, obj):
        self.db.add(obj)

    def add_all(self, objs):
        self.db.add_all(objs)

    def delete(self, obj):
        self.db.delete(obj)

    def commit(self):
        self.db.save()

    def refresh(self, obj):
        pass

    def rollback(self):
        self.db.load()

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

# Global Singleton DB Instance
_GLOBAL_JSON_DB = None

def get_json_db() -> JsonDatabase:
    global _GLOBAL_JSON_DB
    if _GLOBAL_JSON_DB is None:
        _GLOBAL_JSON_DB = JsonDatabase()
    return _GLOBAL_JSON_DB

class EngineDummy:
    def connect(self):
        return self
    def close(self):
        pass

engine = EngineDummy()
SessionLocal = JsonSession
Session = JsonSession

def get_db():
    db = JsonSession()
    try:
        yield db
    finally:
        db.close()
