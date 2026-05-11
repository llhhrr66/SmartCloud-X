import type { RetrievalCitation } from "../types";

type CitationListProps = {
  citations: RetrievalCitation[];
  coverageNotes: string[];
  degraded: boolean;
};

export function CitationList({ citations, coverageNotes, degraded }: CitationListProps) {
  return (
    <section className="result-box">
      <div className="section-header compact">
        <div>
          <div className="eyebrow">Citations</div>
          <h2>Grounding Signals</h2>
        </div>
        {degraded ? <span className="pill warning-pill">degraded</span> : null}
      </div>
      {coverageNotes.length > 0 ? (
        <ul className="coverage-list">
          {coverageNotes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
      {citations.length === 0 ? (
        <p className="empty-cell">No citations yet. Run retrieval to inspect ranking.</p>
      ) : (
        <div className="citation-list">
          {citations.map((citation) => (
            <article className="citation-card" key={citation.chunkId}>
              <div className="citation-topline">
                <strong>{citation.documentTitle ?? citation.title ?? citation.chunkId ?? "Untitled citation"}</strong>
                <span>{(citation.score ?? 0).toFixed(2)}</span>
              </div>
              <p className="service-note">
                {citation.sourceName ?? "-"} · {citation.reasoning ?? "-"}
              </p>
              <p>{citation.snippet ?? citation.content ?? "-"}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
