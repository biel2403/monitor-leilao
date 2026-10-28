import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AnimatePresence, motion } from "framer-motion";

const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const navigation = [
  { id: "opportunities", label: "Oportunidades", note: "Aprovados pela IA", icon: "signal" },
  { id: "lots", label: "Todos os lotes", note: "Catálogo monitorado", icon: "grid" },
  { id: "config", label: "Configurações", note: "Régua de análise", icon: "sliders" },
];

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || body.errors?.join(", ") || `Erro ${response.status}`);
  return body;
}

const asMoney = (value) => value == null ? "Não informado" : money.format(Number(value));
const asDate = (value) => value ? new Date(value).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "Não informado";
const locationText = (item) => item.city && item.state ? `${item.city}/${item.state}` : item.city || item.state || "Local não informado";
const brandFromTitle = (title) => String(title || "").replace(/^(?:I|IMP)\//, "").trim().split(/[\s,/]/)[0].toUpperCase();
const normalizedText = (value) => String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase();
const classificationGroup = (item) => {
  const classification = normalizedText(item.detail?.classification);
  if (classification.includes("PEQUENA MONTA")) return "small_damage";
  if (classification.includes("MEDIA MONTA")) return "medium_damage";
  if (classification.includes("FINANCEIRA")) return "financial";
  return "other";
};

function cost(item) {
  const bid = item.current_bid ?? item.initial_value;
  const detail = item.detail;
  if (bid == null) return { total: null, note: "Lance não informado" };
  if (!detail || detail.commission_percent == null || detail.fixed_fees == null) return { total: null, note: `Lance ${asMoney(bid)}` };
  const commission = Number(bid) * Number(detail.commission_percent) / 100;
  return { total: Number(bid) + commission + Number(detail.fixed_fees), note: `Taxas conhecidas ${asMoney(commission + Number(detail.fixed_fees))}` };
}

function Icon({ name, size = 16 }) {
  const paths = {
    signal: <><path d="M3 17v-2" /><path d="M7 17v-5" /><path d="M11 17V8" /><path d="M15 17V4" /></>,
    grid: <><rect x="3" y="3" width="5" height="5" /><rect x="12" y="3" width="5" height="5" /><rect x="3" y="12" width="5" height="5" /><rect x="12" y="12" width="5" height="5" /></>,
    sliders: <><path d="M4 5h16" /><path d="M4 12h16" /><path d="M4 19h16" /><circle cx="9" cy="5" r="2" /><circle cx="15" cy="12" r="2" /><circle cx="11" cy="19" r="2" /></>,
    refresh: <><path d="M20 11a8 8 0 0 0-14.7-4L3 10" /><path d="M3 5v5h5" /><path d="M4 13a8 8 0 0 0 14.7 4L21 14" /><path d="M21 19v-5h-5" /></>,
    search: <><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></>,
    close: <><path d="m6 6 12 12" /><path d="m18 6-12 12" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function StatusPill({ children, tone = "neutral" }) {
  return <span className={`status-pill status-${tone}`}><span className="status-pill-dot" />{children}</span>;
}

function VehicleIdentity({ item, compact = false }) {
  const image = item.images?.[0] || item.detail?.image_urls?.[0];
  return <div className={`vehicle-identity ${compact ? "vehicle-identity-compact" : ""}`}>
    {image ? <img src={image} alt="" loading="lazy" /> : <span className="vehicle-placeholder" aria-hidden="true">N/D</span>}
    <div className="vehicle-copy"><a href={item.url} target="_blank" rel="noreferrer" title={item.title}>{item.title}</a><small>{[item.year, item.mileage ? `${Number(item.mileage).toLocaleString("pt-BR")} km` : null, locationText(item)].filter(Boolean).join(" · ")}</small></div>
  </div>;
}

function Metric({ label, value, detail, accent = false }) {
  return <div className={`metric ${accent ? "metric-accent" : ""}`}><span className="metric-label">{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}

function CandidateRow({ item }) {
  const current = item.current_bid || item.initial_value;
  const maxBid = item.financial?.max_bid;
  const room = maxBid != null && current != null ? Number(maxBid) - Number(current) : null;
  return <tr>
    <td className="vehicle-cell"><VehicleIdentity item={item} /><span className="row-classification">{item.detail?.classification || "Classificação não informada"}</span></td>
    <td className="money-cell"><strong>{asMoney(current)}</strong><small>lance atual</small></td>
    <td className="money-cell"><strong>{asMoney(item.known_total)}</strong><small>{item.detail?.commission_percent != null ? `${item.detail.commission_percent}% + ${asMoney(item.detail.fixed_fees)}` : "taxas não informadas"}</small></td>
    <td className="money-cell"><strong>{asMoney(item.financial?.fipe_value || item.financial?.reference?.fipe_value)}</strong><small>teto {asMoney(maxBid)}</small></td>
    <td className="money-cell"><strong className={room != null && room >= 0 ? "positive" : "warning"}>{room == null ? "—" : asMoney(room)}</strong><small>folga até o teto</small></td>
    <td className="analysis-cell"><StatusPill tone="good">Bom negócio</StatusPill><small title={item.ai_analysis?.summary}>{item.ai_analysis?.summary || "Aprovado pela régua"}</small></td>
    <td className="date-cell">{asDate(item.closes_at)}</td>
  </tr>;
}

function LotCard({ item, onAnalyze, onOpenAnalysis, busy }) {
  const estimated = cost(item);
  const current = item.current_bid || item.initial_value;
  const analyzed = Boolean(item.ai_analysis);
  const fipe = item.fipe_reference?.fipe_value;
  const image = item.images?.[0] || item.detail?.image_urls?.[0];
  const classification = item.detail?.classification || "Classificação não informada";
  const canAnalyze = item.analysis_supported !== false;
  const vehicleMeta = [item.year, item.mileage ? `${Number(item.mileage).toLocaleString("pt-BR")} km` : null, locationText(item)].filter(Boolean).join(" · ");
  return <article className="lot-card">
    <div className="lot-card-image">{image ? <img src={image} alt="" loading="lazy" /> : <span>IMAGEM N/D</span>}<span className={`lot-card-badge ${item.status === "ABERTO PARA LANCES" ? "badge-good" : "badge-neutral"}`}>{item.status || "Status não informado"}</span></div>
    <div className="lot-card-body">
      <div className="lot-card-topline"><span>{item.source_site || "Fonte não informada"}</span><span>{classification}</span></div>
      <div className="lot-card-title"><a href={item.url} target="_blank" rel="noreferrer" title={item.title}>{item.title}</a><small>{vehicleMeta}</small></div>
      <div className="lot-card-finance"><div className="lot-value"><span>Lance atual</span><strong>{asMoney(current)}</strong></div><div className="lot-value lot-value-emphasis"><span>Custo final</span><strong>{estimated.total == null ? "—" : asMoney(estimated.total)}</strong><small>{estimated.note}</small></div><div className="lot-value"><span>FIPE</span><strong>{fipe == null ? "—" : asMoney(fipe)}</strong><small>{fipe == null ? "Ainda não consultada" : "Valor consultado"}</small></div></div>
      <div className="lot-card-footer"><div className="lot-card-status">{analyzed ? <StatusPill tone={item.analysis_status === "bom_negocio" ? "good" : "pending"}>{item.analysis_status === "bom_negocio" ? "Bom negócio" : item.ai_analysis.decision}</StatusPill> : <span className="analysis-pending">{canAnalyze ? "Análise pendente" : "Análise disponível apenas para carros"}</span>}<small>Encerra {asDate(item.closes_at)}</small></div><button className="analyze-button" disabled={busy || !canAnalyze} onClick={() => analyzed ? onOpenAnalysis(item) : onAnalyze(item)}>{busy ? "Analisando..." : analyzed ? "Ver análise" : canAnalyze ? "Analisar com IA" : "Indisponível"}</button></div>
    </div>
  </article>;
}

function AnalysisDialog({ item, onClose }) {
  if (!item?.ai_analysis) return null;
  const report = item.ai_analysis;
  const decisionLabel = report.decision === "potencial" ? "Bom negócio" : report.decision === "descartar" ? "Descartar" : "Investigar";
  const decisionTone = report.decision === "potencial" ? "good" : "pending";
  const list = (values) => Array.isArray(values) && values.length ? values : ["Nenhuma informação registrada."];
  return <motion.div className="analysis-dialog-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <motion.section className="analysis-dialog" role="dialog" aria-modal="true" aria-labelledby="analysis-dialog-title" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 14 }}>
      <header className="analysis-dialog-header"><div><span className="section-code">LEITURA DA IA</span><h2 id="analysis-dialog-title">{item.title}</h2><p>{item.source_site || "Fonte não informada"} · {item.year || "Ano não informado"}</p></div><button className="icon-button" type="button" aria-label="Fechar análise" onClick={onClose}><Icon name="close" size={18} /></button></header>
      <div className="analysis-dialog-summary"><StatusPill tone={decisionTone}>{decisionLabel}</StatusPill><span>Confiança {report.confidence || "não informada"}</span></div>
      <p className="analysis-dialog-lead">{report.summary || "A IA não forneceu um resumo para este anúncio."}</p>
      <div className="analysis-dialog-grid">
        <section><h3>Critérios aplicados</h3><ul>{list(report.criteria_applied).map((value, index) => <li key={`criteria-${index}`}>{value}</li>)}</ul></section>
        <section><h3>Pontos positivos</h3><ul>{list(report.strengths).map((value, index) => <li key={`strength-${index}`}>{value}</li>)}</ul></section>
        <section><h3>Riscos</h3><ul>{list(report.risks).map((value, index) => <li key={`risk-${index}`}>{value}</li>)}</ul></section>
        <section><h3>Informações pendentes</h3><ul>{list(report.missing_information).map((value, index) => <li key={`missing-${index}`}>{value}</li>)}</ul></section>
      </div>
      <footer className="analysis-dialog-footer"><span>Resultado salvo no catálogo</span><button className="button-secondary" type="button" onClick={onClose}>Fechar</button></footer>
    </motion.section>
  </motion.div>;
}

function App() {
  const [tab, setTab] = useState("opportunities");
  const [data, setData] = useState({ lots: [], candidates: [], sources: [], ai: null });
  const [selectedSource, setSelectedSource] = useState("");
  const [query, setQuery] = useState("");
  const [brandFilter, setBrandFilter] = useState("");
  const [resultFilter, setResultFilter] = useState("all");
  const [classificationFilter, setClassificationFilter] = useState("all");
  const [busyId, setBusyId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [criteria, setCriteria] = useState("");
  const [analysisItem, setAnalysisItem] = useState(null);

  useEffect(() => {
    if (!analysisItem) return undefined;
    const closeOnEscape = (event) => { if (event.key === "Escape") setAnalysisItem(null); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [analysisItem]);

  const load = async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    try {
      const [lots, candidates, sources, ai] = await Promise.all([api("/api/lots"), api("/api/candidates"), api("/api/sources"), api("/api/ai/status")]);
      setData({ lots: lots.items, candidates: candidates.items, sources: sources.items, ai });
      setSelectedSource(sources.selected || sources.items[0]?.key || "");
      setCriteria(ai.criteria || "");
      setMessage(`Sincronizado agora · ${sources.items.find((s) => s.key === sources.selected)?.name || "nenhum site selecionado"}`);
    } catch (error) { setMessage(error.message); }
    finally { if (!silent) setLoading(false); }
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (tab !== "lots") return undefined;
    const interval = window.setInterval(() => load({ silent: true }), 5000);
    return () => window.clearInterval(interval);
  }, [tab]);

  const source = data.sources.find((item) => item.key === selectedSource);
  const brands = useMemo(() => [...new Set(data.lots.map((item) => brandFromTitle(item.title)).filter(Boolean))].sort((a, b) => a.localeCompare(b, "pt-BR")), [data.lots]);
  const visibleLots = useMemo(() => data.lots.filter((item) => {
    const matchesSource = !source || item.source_site === source.name || (source.sample && item.source_site === "fixture-local");
    const needle = query.toLowerCase();
    const matchesQuery = item.title.toLowerCase().includes(needle) || locationText(item).toLowerCase().includes(needle);
    const matchesBrand = !brandFilter || brandFromTitle(item.title) === brandFilter;
    const matchesResult = resultFilter === "all" || (resultFilter === "analyzed" && item.ai_analysis) || (resultFilter === "pending" && !item.ai_analysis) || (resultFilter === "cost" && cost(item).total != null);
    const matchesClassification = classificationFilter === "all" || classificationGroup(item) === classificationFilter;
    return matchesSource && matchesQuery && matchesBrand && matchesResult && matchesClassification;
  }), [data.lots, source, query, brandFilter, resultFilter, classificationFilter]);
  const lotsWithCost = visibleLots.filter((item) => cost(item).total != null).length;
  const analyzedLots = visibleLots.filter((item) => item.ai_analysis).length;
  const currentPage = navigation.find((item) => item.id === tab);

  const analyze = async (item) => {
    setBusyId(item.id); setMessage("Consultando anúncio, FIPE e IA...");
    try { const result = await api(`/api/lots/${item.id}/analyze`, { method: "POST" }); await load(); setAnalysisItem({ ...item, ai_analysis: result.analysis }); setMessage(result.cached ? "Análise recente reaproveitada, sem novo crédito." : "Análise concluída e salva."); }
    catch (error) { setMessage(error.message); }
    finally { setBusyId(null); }
  };
  const updateSource = async () => { try { await api("/api/source", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source: selectedSource }) }); await load(); } catch (error) { setMessage(error.message); } };
  const saveCriteria = async (event) => { event.preventDefault(); try { await api("/api/review-criteria", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ criteria }) }); setMessage("Critérios salvos."); } catch (error) { setMessage(error.message); } };

  return <div className="app-frame">
    <aside className="sidebar">
      <div className="sidebar-brand"><span className="brand-mark" /><div><strong>LEILÃO</strong><small>INTELLIGENCE DESK</small></div></div>
      <div className="sidebar-section-label">Operação</div>
      <nav className="side-nav" aria-label="Navegação principal">{navigation.slice(0, 2).map((item) => <button key={item.id} className={tab === item.id ? "is-active" : ""} onClick={() => setTab(item.id)}><Icon name={item.icon} /><span><strong>{item.label}</strong><small>{item.note}</small></span></button>)}</nav>
      <div className="sidebar-section-label sidebar-section-label-spaced">Sistema</div>
      <nav className="side-nav"><button className={tab === "config" ? "is-active" : ""} onClick={() => setTab("config")}><Icon name="sliders" /><span><strong>Configurações</strong><small>Régua de análise</small></span></button></nav>
      <div className="sidebar-footer"><div className="system-status"><span className="status-dot" />{data.ai?.configured ? "IA conectada" : "IA pendente"}</div><small>Monitoramento sob demanda</small><span className="sidebar-version">LEILÃO / 01</span></div>
    </aside>
    <div className="workspace">
      <header className="workspace-header"><div className="header-title"><span className="header-kicker">{currentPage?.note}</span><h1>{currentPage?.label}</h1><p>Compra e revenda de veículos em leilão</p></div><div className="header-actions"><div className="source-control"><label htmlFor="sourceSelect">Fonte</label><select id="sourceSelect" value={selectedSource} onChange={(event) => setSelectedSource(event.target.value)}>{data.sources.map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}</select><button className="button-secondary" onClick={updateSource}>Aplicar</button></div><button className="refresh-button" onClick={load} disabled={loading}><Icon name="refresh" size={15} />{loading ? "Atualizando" : "Atualizar lotes"}</button></div></header>
      <div className="workspace-status"><span className={loading ? "pulse-dot" : "status-dot"} />{loading ? "Atualizando dados" : message}</div>
      <main className="main"><AnimatePresence mode="wait">
        {tab === "opportunities" && <motion.section key="opportunities" className="view" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><div className="page-head"><div><span className="section-code">01 / OPERAÇÃO</span><h2>Oportunidades</h2><p className="lead">Anúncios aprovados pela IA dentro da sua margem de revenda e do teto calculado com FIPE.</p></div><div className="count-block"><strong>{data.candidates.length}</strong><span>aprovados</span></div></div><div className="metric-strip"><Metric label="Oportunidades aprovadas" value={data.candidates.length} detail="Dentro da margem" accent /><Metric label="Status da IA" value={data.ai?.configured ? "Ativa" : "Pendente"} detail={`${data.ai?.remaining_today ?? "—"} análises restantes`} /><Metric label="Critério aplicado" value="FIPE" detail="−30% até 2019 · −20% desde 2020" /></div><div className="rule-note"><span className="rule-marker" /><strong>Régua ativa</strong><p>FIPE, comissão e despesas publicadas entram no teto. Transporte, reparos e edital devem ser conferidos antes do lance.</p></div><div className="table-heading"><div><strong>Fila de oportunidades</strong><span>{data.candidates.length ? "Ordenada por aprovação da régua" : "Nenhuma aprovação no catálogo atual"}</span></div><span className="table-heading-source">{source?.name || "Fonte não selecionada"}</span></div><div className="table-scroll"><table className="market-table opportunities-table"><thead><tr><th>Veículo e condição</th><th>Lance atual</th><th>Custo conhecido</th><th>Referência FIPE</th><th>Folga até o teto</th><th>Leitura da IA</th><th>Encerra</th></tr></thead><tbody>{data.candidates.length ? data.candidates.map((item) => <CandidateRow key={item.id} item={item} />) : <tr><td colSpan="7" className="empty-state"><strong>Nenhuma oportunidade aprovada ainda</strong><small>Abra “Todos os lotes” e solicite uma análise quando encontrar um anúncio interessante.</small><button className="text-action" onClick={() => setTab("lots")}>Consultar catálogo</button></td></tr>}</tbody></table></div></motion.section>}
        {tab === "lots" && <motion.section key="lots" className="view" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><div className="page-head catalog-page-head"><div><span className="section-code">02 / MONITORAMENTO</span><h2>Todos os lotes</h2><p className="lead">Compare os anúncios monitorados e peça uma leitura da IA somente quando houver potencial.</p></div><div className="count-block"><strong>{visibleLots.length}</strong><span>resultados</span></div></div><div className="catalog-summary"><span><strong>{data.lots.length}</strong> no catálogo</span><span><strong>{lotsWithCost}</strong> custo conhecido</span><span><strong>{analyzedLots}</strong> analisados</span><span className="catalog-source">{source?.name || "Fonte não selecionada"}</span></div><div className="search-panel"><div className="search-main"><label htmlFor="lotSearch"><Icon name="search" size={14} /> Buscar por veículo ou local</label><input id="lotSearch" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Jetta, T-Cross, São Paulo..." /></div><label>Marca<select value={brandFilter} onChange={(event) => setBrandFilter(event.target.value)}><option value="">Todas as marcas</option>{brands.map((brand) => <option key={brand} value={brand}>{brand}</option>)}</select></label><label>Mostrar<select value={resultFilter} onChange={(event) => setResultFilter(event.target.value)}><option value="all">Todos os lotes</option><option value="pending">Ainda não analisados</option><option value="analyzed">Já analisados</option><option value="cost">Com custo conhecido</option></select></label><div className="classification-filter"><span>Classificação</span><div className="choice-buttons" role="group" aria-label="Filtrar por classificação"><button type="button" className={classificationFilter === "all" ? "is-selected" : ""} aria-pressed={classificationFilter === "all"} onClick={() => setClassificationFilter("all")}>Todas</button><button type="button" className={classificationFilter === "financial" ? "is-selected" : ""} aria-pressed={classificationFilter === "financial"} onClick={() => setClassificationFilter("financial")}>Financeira</button><button type="button" className={classificationFilter === "medium_damage" ? "is-selected" : ""} aria-pressed={classificationFilter === "medium_damage"} onClick={() => setClassificationFilter("medium_damage")}>Média monta</button><button type="button" className={classificationFilter === "small_damage" ? "is-selected" : ""} aria-pressed={classificationFilter === "small_damage"}>Pequena monta</button></div></div>{(query || brandFilter || resultFilter !== "all" || classificationFilter !== "all") && <button className="button-secondary clear-filters" onClick={() => { setQuery(""); setBrandFilter(""); setResultFilter("all"); setClassificationFilter("all"); }}>Limpar filtros</button>}</div><div className="table-heading"><div><strong>Catálogo de veículos</strong><span>Cards ampliados · valores em BRL · dados ausentes aparecem como “—”</span></div><span className="table-heading-source">{visibleLots.length} de {data.lots.length}</span></div><div className="lot-card-grid">{visibleLots.length ? visibleLots.map((item) => <LotCard key={item.id} item={item} onAnalyze={analyze} onOpenAnalysis={setAnalysisItem} busy={busyId === item.id} />) : <div className="empty-state"><strong>Nenhum lote encontrado</strong><small>Ajuste a busca ou limpe os filtros para consultar o catálogo completo.</small></div>}</div></motion.section>}
        {tab === "config" && <motion.section key="config" className="view" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><div className="page-head"><div><span className="section-code">03 / SISTEMA</span><h2>Configurações</h2><p className="lead">Ajuste a régua usada pela IA para encontrar margem de revenda.</p></div><StatusPill tone={data.ai?.configured ? "good" : "pending"}>{data.ai?.configured ? "IA conectada" : "IA pendente"}</StatusPill></div><div className="settings-shell"><section className="settings-section"><div className="settings-heading"><div><span className="section-code">CRITÉRIO PRINCIPAL</span><h3>Régua de revenda</h3><p>A instrução abaixo é enviada junto dos dados do anúncio, FIPE e taxas conhecidas.</p></div><span className="settings-status">Salva no servidor</span></div><form onSubmit={saveCriteria}><label htmlFor="criteria">Instruções para a análise</label><textarea id="criteria" value={criteria} onChange={(event) => setCriteria(event.target.value)} rows="8" /><div className="form-footer"><small>Defina como a IA deve classificar um lote como bom negócio.</small><button type="submit">Salvar critérios</button></div></form></section><section className="settings-section settings-usage"><div><span className="section-code">CONSUMO</span><h3>Análise sob demanda</h3><p>A análise só acontece quando solicitada no lote. Resultados recentes são reaproveitados para evitar novos créditos.</p></div><div className="usage-readout"><strong>{data.ai?.remaining_today ?? "—"}</strong><span>análises restantes hoje</span></div></section></div></motion.section>}
      </AnimatePresence></main>
    </div>
    <AnimatePresence>{analysisItem && <AnalysisDialog item={analysisItem} onClose={() => setAnalysisItem(null)} />}</AnimatePresence>
  </div>;
}

createRoot(document.getElementById("root")).render(<App />);

