from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import re
from typing import Iterable

from app.core.config import get_settings
from app.models import ResearchCitation, ResearchResult, ResearchSection, ResearchTask


@dataclass(frozen=True)
class RenderedResearchArtifact:
    report_file_id: str
    file_path: Path
    download_url: str
    preview_text: str
    sections: list[ResearchSection]
    citations: list[ResearchCitation]
    metadata: dict[str, object]


class ResearchExportRenderer:
    def __init__(self) -> None:
        settings = get_settings()
        artifact_root = (settings.bootstrap_path.parent if settings.bootstrap_path else Path(__file__).resolve().parents[2] / "data")
        self._artifact_root = artifact_root / "exports"
        self._artifact_root.mkdir(parents=True, exist_ok=True)
        self._download_base_url = settings.report_download_base_url.rstrip("/")

    def render(self, task: ResearchTask, result: ResearchResult) -> RenderedResearchArtifact:
        report_file_id = self._report_file_id(task)
        markdown_body = self._render_markdown(task, result)
        if task.output_format == "pdf":
            file_path = self._artifact_root / f"{report_file_id}.pdf"
            file_bytes = self._render_pdf_bytes(task, markdown_body)
            file_path.write_bytes(file_bytes)
            preview_text = markdown_body[:4000]
        else:
            file_path = self._artifact_root / f"{report_file_id}.md"
            file_path.write_text(markdown_body, encoding="utf-8")
            preview_text = markdown_body[:4000]
        metadata = {
            **{str(key): value for key, value in result.metadata.items()},
            "artifact_path": str(file_path),
            "artifact_bytes": file_path.stat().st_size,
            "rendered_format": task.output_format,
            "artifact_checksum_sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
        }
        return RenderedResearchArtifact(
            report_file_id=report_file_id,
            file_path=file_path,
            download_url=f"{self._download_base_url}/{report_file_id}.{self._file_extension(task.output_format)}",
            preview_text=preview_text,
            sections=list(result.sections),
            citations=list(result.citations),
            metadata=metadata,
        )

    def _render_markdown(self, task: ResearchTask, result: ResearchResult) -> str:
        lines: list[str] = [
            f"# {task.topic}",
            "",
            "## 摘要",
            result.summary,
            "",
            "## 研究范围",
            task.scope,
            "",
            "## 任务配置",
            f"- 深度: {task.depth}",
            f"- 输出格式: {task.output_format}",
            f"- 引用数量: {len(result.citations)}",
        ]
        if getattr(task, "reference_urls", None):
            lines.extend(["", "## 输入参考链接"])
            lines.extend(f"- {url}" for url in task.reference_urls)
        for section in result.sections:
            lines.extend(["", f"## {section.title}", section.content])
        if result.citations:
            lines.extend(["", "## 引用"])
            for index, citation in enumerate(result.citations, start=1):
                lines.append(f"{index}. [{citation.title}]({citation.url})")
                if citation.snippet:
                    lines.append(f"   - 摘要: {citation.snippet}")
        if result.metadata:
            lines.extend(["", "## 元数据"])
            for key, value in result.metadata.items():
                lines.append(f"- {key}: {value}")
        return "\n".join(lines).strip() + "\n"

    def _render_pdf_bytes(self, task: ResearchTask, markdown_body: str) -> bytes:
        payload = {
            "topic": task.topic,
            "output_format": task.output_format,
            "markdown": markdown_body,
        }
        payload_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        payload_bytes = payload_text.encode("utf-8")
        stream = b"BT /F1 12 Tf 50 780 Td (Research export fallback - see EmbeddedJSON metadata) Tj ET\n"
        objects = [
            b"1 0 obj << /Type /Catalog /Pages 2 0 R /Names << /EmbeddedFiles 7 0 R >> >> endobj\n",
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n",
            f"4 0 obj << /Length {len(stream)} >> stream\n".encode("latin-1") + stream + b"endstream\nendobj\n",
            b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
            (
                f"6 0 obj << /Type /EmbeddedFile /Subtype /application#2Fjson /Length {len(payload_bytes)} >> stream\n".encode("latin-1")
                + payload_bytes
                + b"\nendstream\nendobj\n"
            ),
            b"7 0 obj << /Names [(research-export.json) 8 0 R] >> endobj\n",
            b"8 0 obj << /Type /Filespec /F (research-export.json) /EF << /F 6 0 R >> /Desc (EmbeddedJSON markdown export) >> endobj\n",
        ]
        pdf = bytearray(b"%PDF-1.4\n")
        offsets: list[int] = []
        for obj in objects:
            offsets.append(len(pdf))
            pdf.extend(obj)
        xref_offset = len(pdf)
        pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
        pdf.extend(b"0000000000 65535 f \n")
        for offset in offsets:
            pdf.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
        pdf.extend(
            (
                f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n"
            ).encode("latin-1")
        )
        return bytes(pdf)

    @staticmethod
    def _pdf_escape(value: str) -> str:
        normalized = value.replace("\r\n", "\n").replace("\r", "\n")
        normalized = normalized.encode("latin-1", errors="replace").decode("latin-1")
        escaped = normalized.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        return escaped.replace("\n", r"\n")

    def _report_file_id(self, task: ResearchTask) -> str:
        digest = hashlib.sha256(f"{task.task_id}:{task.topic}:{task.output_format}".encode("utf-8")).hexdigest()[:10]
        slug = self._slugify(task.topic)
        return f"research_{slug}_{digest}"

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value.strip().lower())
        normalized = re.sub(r"-+", "-", normalized).strip("-")
        return normalized[:48] or "report"

    @staticmethod
    def _file_extension(output_format: str) -> str:
        return "pdf" if output_format == "pdf" else "md"


def render_research_artifact(task: ResearchTask, result: ResearchResult) -> RenderedResearchArtifact:
    return ResearchExportRenderer().render(task, result)
