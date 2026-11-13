# Interfaces de los adaptadores (puertos)

Viven en `src/security_vision/core/interfaces/`. Son clases abstractas (`abc.ABC`) con tipos de dominio puros. El resto del sistema solo depende de estas firmas. Lo que sigue es un **borrador de diseño**: el código definitivo se escribe en la Fase 1, junto con tests de contrato que todo adaptador debe pasar.

## Tipos comunes

```python
class Frame:                       # contenedor ligero, sin acoplarse a OpenCV
    data: np.ndarray               # HxWxC uint8, RGB
    frame_id: int
    captured_at: datetime          # reloj monotónico convertido a UTC
    source_pts: float | None       # timestamp de presentación de la fuente
    width: int; height: int

class SourceStatus(StrEnum): DISCONNECTED, CONNECTING, CONNECTED, DEGRADED, ERROR
class DeviceInfo(BaseModel): kind: Literal["cpu","cuda","tensorrt","openvino-cpu","openvino-gpu",...]; name: str; memory_mb: int | None
```

## VideoSource

```python
class VideoSource(ABC):
    provider_name: ClassVar[str]               # "ffmpeg", "gstreamer", "opencv", "file"
    def __init__(self, config: VideoSourceConfig) -> None: ...
    @abstractmethod
    def connect(self) -> None: ...             # lanza VideoSourceError tipado
    @abstractmethod
    def disconnect(self) -> None: ...
    @abstractmethod
    def read_frame(self, timeout: float) -> Frame | None: ...   # None = no hay fotograma en el plazo
    @abstractmethod
    def get_metadata(self) -> SourceMetadata: ...  # códec, resolución, fps nominal
    @abstractmethod
    def get_status(self) -> SourceStatus: ...
    @classmethod
    def capabilities(cls) -> SourceCapabilities: ...  # protocolos admitidos (usb, rtsp, file...), hwaccel

class CameraDiscovery(ABC):                     # opcional: ONVIF WS-Discovery, USB
    def discover(self, timeout: float) -> list[DiscoveredCamera]: ...
```

La reconexión **no** es responsabilidad del adaptador: la gestiona `CameraSupervisor` con *backoff* exponencial y *jitter*. Así cada adaptador queda simple y el comportamiento es uniforme.

## InferenceEngine

Ejecuta un grafo con tensores; no sabe nada de detección.

```python
class InferenceEngine(ABC):
    provider_name: ClassVar[str]               # "onnxruntime", "openvino", ...
    @abstractmethod
    def load_model(self, artifact: ModelArtifact, device: DeviceRequest) -> None: ...
    @abstractmethod
    def predict(self, inputs: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]: ...
    @abstractmethod
    def get_device(self) -> DeviceInfo: ...
    @abstractmethod
    def get_metrics(self) -> EngineMetrics: ...  # latencias p50/p95, nº de llamadas, memoria
    @abstractmethod
    def unload_model(self) -> None: ...
    @classmethod
    def available_devices(cls) -> list[DeviceInfo]: ...  # p. ej. ORT: CPU, CUDA, TensorRT si están instalados
```

`DeviceRequest` admite una lista de preferencia (`["tensorrt", "cuda", "cpu"]`) con *fallback* explícito y registrado en el log. Pasar de CPU a TensorRT es solo un cambio de configuración.

## DetectionModel

Encapsula lo específico del modelo (pre/post-proceso, mapa de clases) y **usa** un `InferenceEngine` inyectado. Esto separa *qué modelo* de *qué motor*.

```python
class DetectionModel(ABC):
    architecture: ClassVar[str]                # "rtdetr", "rfdetr", "yolox", ...
    def __init__(self, spec: ModelSpec, engine: InferenceEngine) -> None: ...
    @abstractmethod
    def detect(self, frames: Sequence[Frame]) -> list[list[Detection]]: ...  # admite batch
    @abstractmethod
    def classes(self) -> ClassMap: ...         # mapea las clases del modelo a las canónicas
    def warmup(self) -> None: ...
```

`ClassMap` traduce las etiquetas propias de cada modelo (p. ej. `"hardhat"`, `"Helmet"`) a las **clases canónicas** del dominio (`person`, `helmet`, `vest`, `boots`, …). Un modelo personalizado se añade con un archivo `model.yaml` + `.onnx`, sin escribir código, siempre que use una arquitectura ya soportada.

## ObjectTracker

```python
class ObjectTracker(ABC):
    provider_name: ClassVar[str]               # "bytetrack", ...
    @abstractmethod
    def update(self, detections: Sequence[Detection], frame_ts: datetime) -> list[Track]: ...
    @abstractmethod
    def reset(self) -> None: ...
    @abstractmethod
    def get_tracks(self) -> list[Track]: ...    # activos + perdidos recientemente
```

Habrá una instancia por cámara. Las personas se trackean; los EPP se asocian a ellas, aunque opcionalmente también pueden trackearse para suavizar.

## PPEAssociator

```python
class PPEAssociator(ABC):
    def associate(self, persons: Sequence[Track], items: Sequence[Detection]) -> dict[int, list[Detection]]: ...
```

## SecurityEvaluator y reglas

```python
class PPERule(ABC):                            # una por clase de EPP: casco, chaleco, botas...
    ppe_class: ClassVar[str]
    def region_of_interest(self, person: BBox) -> BBox: ...
    def is_verifiable(self, person: Track, frame_size: Size, context: SceneContext) -> Verifiability: ...
    def observe(self, person: Track, associated: Sequence[Detection], ctx: SceneContext) -> Observation: ...

class SecurityEvaluator(ABC):
    @abstractmethod
    def evaluate(self, tracks: Sequence[Track], associations: Mapping[int, Sequence[Detection]],
                 ctx: EvaluationContext) -> EvaluationResult: ...   # incluye las transiciones
    @abstractmethod
    def get_violations(self) -> list[Violation]: ...
    @abstractmethod
    def get_compliance_status(self, track_id: int | None = None) -> list[PersonCompliance]: ...
```

## AnalysisPipeline (puerto de grano grueso)

```python
class AnalysisPipeline(ABC):                   # default: ModularPipeline(VideoSource, DetectionModel, Tracker)
    def start(self) -> None: ...               # futuro: DeepStreamPipeline
    def stop(self) -> None: ...
    def results(self) -> Iterator[AnalyzedFrame]: ...  # Tracks + asociaciones + metadatos de tiempo
```

## Infraestructura

```python
class ObjectStorage(ABC):        # LocalFileStorage → S3Storage
    def put(self, key: str, data: bytes | BinaryIO, content_type: str) -> StoredObject: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def signed_url(self, key: str, ttl: timedelta) -> str: ...
    def list(self, prefix: str, older_than: datetime | None = None) -> Iterator[StoredObject]: ...

class MessageBus(ABC):           # InProcessBus → ValkeyStreamsBus → NatsBus
    async def publish(self, event: DomainEvent) -> None: ...
    def subscribe(self, event_types: Sequence[str], group: str) -> AsyncIterator[DomainEvent]: ...

class AlertChannel(ABC):         # UiChannel, EmailChannel, WebhookChannel, TelegramChannel...
    channel_type: ClassVar[str]
    async def send(self, alert: Alert) -> DeliveryResult: ...
```

## Registro de proveedores

```python
registry.register(VideoSource, "ffmpeg", FfmpegVideoSource)
source = registry.create(VideoSource, cfg.provider, cfg)   # cfg viene de BD/YAML
```

Los plugins se declaran en `pyproject.toml`:

```toml
[project.entry-points."security_vision.video_sources"]
ffmpeg = "security_vision.plugins.video_sources.ffmpeg_pyav:FfmpegVideoSource"
```

## Eventos de dominio (versionados)

`camera.status_changed.v1`, `frame.analyzed.v1` (muestreado, para la UI), `person.compliance_changed.v1`, `incident.confirmed.v1`, `incident.updated.v1`, `incident.closed.v1`, `model.loaded.v1`. Todos llevan `event_id`, `occurred_at`, `camera_id`, `schema_version` y `correlation_id`.
