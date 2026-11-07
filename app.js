(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const PASSO = 60;                      // cartões por vez na vista de setor

  // ---- armazenamento seguro ----
  const store = {
    ler(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
    gravar(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }
  };
  const chave = (i) => `${i.fonte}:${i.id}`;
  let lista = new Map(store.ler("sl_lista2", []).map((i) => [chave(i), i]));   // guarda o item inteiro

  // ---- estado ----
  let linhasHome = [];                   // [{titulo, itens, setor?, total?}]
  let setores = new Map();               // id -> {id,titulo,total,salvos,partes}
  const partes = new Map();              // "id-n" -> itens normalizados
  let todosCarregados = null;            // lista global (busca), carregada sob demanda
  let atual = null, heroItem = null, vista = null;

  const norm = (c) => ({
    fonte: "archive", id: c.i, titulo: c.t, ano: c.a, duracao: c.r, descricao: c.s,
    poster: `https://archive.org/services/img/${encodeURIComponent(c.i)}`
  });

  async function getJson(url) {
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok) throw new Error(url + " " + r.status);
    return r.json();
  }
  async function parte(id, n) {
    const k = `${id}-${n}`;
    if (!partes.has(k)) partes.set(k, (await getJson(`setores/${k}.json`)).map(norm));
    return partes.get(k);
  }

  // ---- player ----
  function montarPlayer(i) {
    if (i.fonte === "commons") {
      const v = document.createElement("video");
      v.controls = true; v.autoplay = true; v.playsInline = true; v.poster = i.poster || "";
      const s = document.createElement("source");
      s.src = i.url; s.type = i.tipo || "video/webm";
      v.appendChild(s);
      return v;
    }
    const f = document.createElement("iframe");
    f.allow = "autoplay; fullscreen; picture-in-picture; encrypted-media";
    f.allowFullscreen = true;
    f.referrerPolicy = "strict-origin-when-cross-origin";
    f.src = i.fonte === "youtube"
      ? `https://www.youtube-nocookie.com/embed/${encodeURIComponent(i.id)}?autoplay=1&rel=0`
      : `https://archive.org/embed/${encodeURIComponent(i.id)}`;
    return f;
  }
  const origem = (i) =>
    i.fonte === "youtube" ? `https://www.youtube.com/watch?v=${encodeURIComponent(i.id)}`
    : i.fonte === "commons" ? (i.pagina || i.url)
    : `https://archive.org/details/${encodeURIComponent(i.id)}`;
  const nomeFonte = { archive: "Internet Archive", commons: "Wikimedia Commons", youtube: "YouTube" };
  const metaHtml = (i) => [i.ano && `<b>${esc(i.ano)}</b>`, i.duracao && esc(i.duracao), esc(nomeFonte[i.fonte] || "")]
    .filter(Boolean).join(" · ");

  // ---- cartões e linhas ----
  function cartao(i) {
    const el = document.createElement("article");
    el.className = "card";
    el.tabIndex = 0;
    el.innerHTML = `<div class="poster" style="background-image:url('${esc(i.poster)}')"></div>
      <div class="rotulo"><div class="nome">${esc(i.titulo)}</div><div class="ano">${esc(i.ano || "")}</div></div>`;
    const abrir = () => abrirModal(i);
    el.addEventListener("click", abrir);
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") abrir(); });
    return el;
  }

  function linha(l) {
    const sec = document.createElement("section");
    sec.className = "linha";
    const ver = l.setor ? `<a class="ver-todos" href="#setor=${encodeURIComponent(l.setor)}">Ver todos (${(l.total || 0).toLocaleString("pt-BR")}) ›</a>` : "";
    sec.innerHTML = `<h2><span>${esc(l.titulo)}</span>${ver}</h2>
      <div class="faixa"><button class="seta esq" aria-label="Anterior">‹</button>
      <div class="trilho"></div><button class="seta dir" aria-label="Próximo">›</button></div>`;
    const trilho = sec.querySelector(".trilho");
    l.itens.forEach((i) => trilho.appendChild(cartao(i)));
    const passo = () => Math.max(trilho.clientWidth * 0.85, 200);
    sec.querySelector(".esq").onclick = () => trilho.scrollBy({ left: -passo(), behavior: "smooth" });
    sec.querySelector(".dir").onclick = () => trilho.scrollBy({ left: passo(), behavior: "smooth" });
    return sec;
  }

  function grade(itens) {
    const g = document.createElement("div");
    g.className = "resultados";
    itens.forEach((i) => g.appendChild(cartao(i)));
    return g;
  }

  // ---- telas ----
  function renderHome() {
    vista = null;
    const alvo = $("linhas");
    alvo.replaceChildren();
    $("hero").hidden = !heroItem;
    alvo.classList.toggle("sem-hero", !heroItem);
    if (lista.size) alvo.appendChild(linha({ titulo: "Minha lista", itens: [...lista.values()] }));
    linhasHome.forEach((l) => alvo.appendChild(linha(l)));
    if (!linhasHome.length) alvo.innerHTML = '<p class="vazio">Catálogo vazio. Rode os workflows no GitHub Actions.</p>';
  }

  async function renderSetor(id) {
    const s = setores.get(id);
    $("hero").hidden = true;
    const alvo = $("linhas");
    alvo.classList.add("sem-hero");
    alvo.replaceChildren();
    if (!s) { alvo.innerHTML = '<p class="vazio">Setor não encontrado. <a href="#">Voltar</a></p>'; return; }

    vista = { id, itens: [], proxima: 0, mostrados: 0 };
    const sec = document.createElement("section");
    sec.className = "linha";
    sec.innerHTML = `<h2><a class="voltar" href="#">‹ Início</a><span>${esc(s.titulo)}</span>
      <small>${s.salvos.toLocaleString("pt-BR")} títulos</small></h2>
      <div id="vista-grade"></div><button class="btn cinza mais" id="vista-mais" hidden>Mostrar mais</button>`;
    alvo.appendChild(sec);
    await maisDoSetor();
    $("vista-mais").onclick = maisDoSetor;
    window.scrollTo(0, 0);
  }

  async function maisDoSetor() {
    const v = vista, s = v && setores.get(v.id);
    if (!v) return;
    const btn = $("vista-mais");
    btn.disabled = true;
    try {
      while (v.itens.length < v.mostrados + PASSO && v.proxima < s.partes) {
        v.itens.push(...(await parte(v.id, v.proxima++)));
      }
    } catch { btn.textContent = "Erro ao carregar. Tentar de novo"; btn.disabled = false; btn.hidden = false; return; }
    if (vista !== v) return;               // usuário saiu da vista
    const novos = v.itens.slice(v.mostrados, v.mostrados + PASSO);
    v.mostrados += novos.length;
    novos.forEach((i) => $("vista-grade").appendChild(cartao(i)));
    $("vista-grade").classList.add("resultados");
    btn.textContent = "Mostrar mais";
    btn.disabled = false;
    btn.hidden = !(v.mostrados < v.itens.length || v.proxima < s.partes);
  }

  async function carregarTudo() {
    if (todosCarregados) return todosCarregados;
    const mapa = new Map();
    linhasHome.forEach((l) => l.itens.forEach((i) => mapa.set(chave(i), i)));
    const jobs = [];
    for (const s of setores.values()) for (let n = 0; n < s.partes; n++) jobs.push(parte(s.id, n));
    (await Promise.allSettled(jobs)).forEach((r) => {
      if (r.status === "fulfilled") r.value.forEach((i) => { if (!mapa.has(chave(i))) mapa.set(chave(i), i); });
    });
    return (todosCarregados = [...mapa.values()]);
  }

  async function renderBusca(q) {
    vista = null;
    $("hero").hidden = true;
    const alvo = $("linhas");
    alvo.classList.add("sem-hero");
    alvo.innerHTML = '<p class="vazio">Buscando em todo o catálogo…</p>';
    const todos = await carregarTudo();
    if ($("busca").value.trim().toLowerCase() !== q) return;     // busca mudou enquanto carregava
    const termos = q.split(/\s+/);
    const achados = todos.filter((i) => {
      const t = `${i.titulo} ${i.ano || ""}`.toLowerCase();
      return termos.every((w) => t.includes(w));
    });
    alvo.replaceChildren();
    const sec = document.createElement("section");
    sec.className = "linha";
    sec.innerHTML = `<h2><span>Resultados para "${esc(q)}"</span><small>${achados.length.toLocaleString("pt-BR")}</small></h2>`;
    if (achados.length) {
      sec.appendChild(grade(achados.slice(0, 300)));
      if (achados.length > 300) sec.insertAdjacentHTML("beforeend", '<p class="vazio">Mostrando os 300 primeiros. Refine a busca.</p>');
    } else sec.insertAdjacentHTML("beforeend", '<p class="vazio">Nada encontrado.</p>');
    alvo.appendChild(sec);
  }

  function rotear() {
    const q = $("busca").value.trim().toLowerCase();
    const m = location.hash.match(/^#setor=(.+)$/);
    if (q) return renderBusca(q);
    if (m) return renderSetor(decodeURIComponent(m[1]));
    renderHome();
  }
  window.addEventListener("hashchange", () => { $("busca").value = ""; rotear(); });

  // ---- destaque ----
  function escolherHero(itens) {
    const c = itens.filter((i) => i.descricao && i.descricao.length > 40 && i.poster).slice(0, 12);
    return c.length ? c[Math.floor(Date.now() / 86400000) % c.length] : null;
  }
  function mostrarHero() {
    if (!heroItem) return;
    $("hero-bg").style.backgroundImage = `url('${heroItem.poster}')`;
    $("hero-titulo").textContent = heroItem.titulo;
    $("hero-meta").innerHTML = metaHtml(heroItem);
    $("hero-desc").textContent = heroItem.descricao;
    botaoLista($("hero-lista"), heroItem);
  }

  // ---- minha lista ----
  function botaoLista(btn, i) { btn.textContent = lista.has(chave(i)) ? "✓ Na minha lista" : "＋ Minha lista"; }
  function alternarLista(i) {
    const k = chave(i);
    lista.has(k) ? lista.delete(k) : lista.set(k, i);
    store.gravar("sl_lista2", [...lista.values()]);
    if (heroItem) botaoLista($("hero-lista"), heroItem);
    if (atual) botaoLista($("m-lista"), atual);
    if (!vista && !$("busca").value.trim()) renderHome();
  }
  $("hero-lista").onclick = () => heroItem && alternarLista(heroItem);
  $("m-lista").onclick = () => atual && alternarLista(atual);
  $("hero-assistir").onclick = () => heroItem && abrirModal(heroItem);

  // ---- modal ----
  function abrirModal(i) {
    atual = i;
    $("tela").replaceChildren(montarPlayer(i));
    $("m-titulo").textContent = i.titulo;
    $("m-meta").innerHTML = metaHtml(i);
    $("m-desc").textContent = i.descricao || "";
    $("m-origem").href = origem(i);
    botaoLista($("m-lista"), i);
    $("modal").hidden = false;
    document.body.style.overflow = "hidden";
    $("fechar").focus();
  }
  function fecharModal() {
    $("tela").replaceChildren();
    $("modal").hidden = true;
    document.body.style.overflow = "";
    atual = null;
  }
  $("fechar").onclick = fecharModal;
  $("modal").addEventListener("click", (e) => { if (e.target === $("modal")) fecharModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("modal").hidden) fecharModal(); });

  // ---- barra e busca ----
  window.addEventListener("scroll", () => $("nav").classList.toggle("solida", window.scrollY > 40), { passive: true });
  let t;
  $("busca").addEventListener("input", () => { clearTimeout(t); t = setTimeout(rotear, 250); });

  // ---- início ----
  async function iniciar() {
    const [indice, filmes] = await Promise.all([
      getJson("indice.json").catch(() => ({ setores: [] })),
      getJson("filmes.json").catch(() => ({ linhas: [] }))
    ]);

    (filmes.linhas || []).forEach((l) => linhasHome.push({ titulo: l.titulo, itens: l.itens }));
    (indice.setores || []).forEach((s) => {
      setores.set(s.id, s);
      linhasHome.push({ titulo: s.titulo, itens: s.destaque.map(norm), setor: s.id, total: s.salvos });
    });

    heroItem = escolherHero(linhasHome.flatMap((l) => l.itens));
    mostrarHero();
    rotear();

    const total = [...setores.values()].reduce((n, s) => n + s.salvos, 0) +
      (filmes.linhas || []).reduce((n, l) => n + l.itens.length, 0);
    const quando = indice.atualizadoEm || filmes.atualizadoEm;
    if (total) $("rodape").textContent =
      `${total.toLocaleString("pt-BR")} títulos de fontes públicas` +
      (quando ? ` · atualizado em ${new Date(quando).toLocaleDateString("pt-BR")}` : "");
  }
  iniciar();
})();
