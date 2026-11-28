// Embedded inside the reader closure by mcr.build.
const chapters = DATA.structure.chapters || [];
const edges = DATA.structure.edges || [];
const params = () => new URLSearchParams(location.hash.slice(1));
const currentChapter = () => chapters.find(c => c.id === params().get("chapter")) || chapters[0];
const caption = (zh, en) => state.lang === "zh" ? zh : en;

function el(tag, cls, value) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (value) node.textContent = value;
  return node;
}
function link(values, label, cls) {
  const a = el("a", cls, label);
  a.href = "#" + new URLSearchParams(values);
  return a;
}
function chapterLink(chapter, label, cls) {
  return link({chapter: chapter.id}, label, cls);
}
function evidence(file, start, end, label) {
  const target = {file, start, end};
  if (chapters.length && params().has("chapter")) target.chapter = currentChapter().id;
  return link(target, label, "source-link");
}

function renderTutorial(container) {
  if (!chapters.length) return;
  const selected = currentChapter();
  const lang = state.lang;
  const guide = el("section", "guide");
  const map = el("nav", "map");
  map.setAttribute("aria-label", caption("架构图", "Architecture map"));
  map.append(el("h3", "", caption("架构图", "Architecture map")));
  // Each row is a concept. Arcs use separate lanes so branches and feedback
  // can reach their actual targets without implying a linear runtime pipeline.
  const graph = el("div", "graph");
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  const width = 18 + Math.min(edges.length, 8) * 5;
  const rowHeight = 46;
  svg.setAttribute("width", width);
  svg.setAttribute("height", chapters.length * rowHeight);
  svg.setAttribute("aria-hidden", "true");
  graph.style.setProperty("--rail", width + "px");
  graph.append(svg);
  edges.forEach((edge, i) => {
    const y = id => (chapters.findIndex(c => c.id === id) + 0.5) * rowHeight;
    const from = y(edge.from) - 3, to = y(edge.to) + 3;
    const lane = width - 12 - (i % 8) * 5;
    const p = document.createElementNS(svgNS, "path");
    p.setAttribute("d", `M ${width} ${from} H ${lane} V ${to} H ${width-2} m -4 -3 l 4 3 -4 3`);
    p.setAttribute("class", edge.from === selected.id || edge.to === selected.id ? "related" : "");
    const title = document.createElementNS(svgNS, "title");
    title.textContent = edge[lang];
    p.append(title);
    svg.append(p);
  });
  chapters.forEach(ch => {
    const node = chapterLink(ch, ch.title[lang], "concept");
    if (ch === selected) node.setAttribute("aria-current", "step");
    graph.append(node);
  });
  map.append(graph);
  const lesson = el("article", "lesson");
  lesson.append(el("h3", "", selected.title[lang]));
  const body = el("p");
  body.innerHTML = renderMarkdownLite(selected.body[lang]);
  lesson.append(body);
  for (const ref of selected.refs) {
    const a = evidence(ref.file, ref.start, ref.end, ref[lang]);
    // Retain chapter context even on the initial, hashless overview.
    a.href = "#" + new URLSearchParams({file:ref.file, start:ref.start, end:ref.end, chapter:selected.id});
    a.append(el("small", "", ref.file + " · L" + ref.start + "–" + ref.end));
    lesson.append(a);
  }
  const relations = el("div", "relations");
  for (const edge of edges.filter(e => e.from === selected.id || e.to === selected.id)) {
    const outgoing = edge.from === selected.id;
    const other = chapters.find(c => c.id === (outgoing ? edge.to : edge.from));
    relations.append(chapterLink(other, (outgoing ? "→ " : "← ") + other.title[lang] + " · " + edge[lang]));
  }
  lesson.append(relations);
  const i = chapters.indexOf(selected), steps = el("div", "steps");
  if (i) steps.append(chapterLink(chapters[i-1], caption("‹ 上一章", "‹ Previous")));
  if (i+1 < chapters.length) steps.append(chapterLink(chapters[i+1], caption("下一章 ›", "Next ›")));
  lesson.append(steps);
  guide.append(map, lesson);
  container.append(guide);
}

function renderFileIntro(file, note) {
  note.replaceChildren();
  note.classList.add("visible");
  const left = el("div", "file-heading");
  left.append(el("small", "", caption("源代码", "Source")), el("h2", "", file.path.split("/").pop()));
  if (chapters.length && params().has("chapter"))
    left.append(chapterLink(currentChapter(), "‹ " + currentChapter().title[state.lang]));
  // Show the implementation the tutorial discusses while the outline is open.
  const relevant = chapters.flatMap(ch => ch.refs.filter(r => r.file === file.path));
  if (relevant.length) {
    const ref = relevant[0];
    left.append(evidence(file.path, ref.start, ref.end, ref[state.lang]));
    const code = highlightLines(file.code, file.language);
    const preview = el("div", "preview");
    for (let n = ref.start; n <= Math.min(ref.end, ref.start + 6); n++) {
      const line = el("div");
      line.append(el("span", "preview-number", String(n)));
      const token = el("code");
      token.innerHTML = code[n - 1];
      line.append(token);
      preview.append(line);
    }
    left.append(preview);
  }
  const right = el("section", "file-intro");
  right.append(el("h3", "", caption("文件导读", "File guide")));
  const description = (DATA.structure.files || {})[file.path];
  const text = file["note_" + state.lang] || (description && description[state.lang]);
  if (text) {
    const p = el("p");
    p.innerHTML = renderMarkdownLite(text);
    right.append(p);
  } else if (!file.blocks.length) right.append(el("p", "", t("noAnnotation")));
  if (file.symbols.length) {
    const outline = el("details", "outline");
    outline.open = true;
    outline.append(el("summary", "", caption("类与函数", "Classes and functions")));
    file.symbols.forEach(sym => {
      const a = evidence(file.path, sym.start, sym.end, sym.name);
      if (sym.name.includes(".")) a.classList.add("method");
      if (sym[state.lang]) a.append(el("small", "", sym[state.lang]));
      outline.append(a);
    });
    right.append(outline);
  }
  note.append(left, right);
}

function followLocation() {
  const q = params();
  const idx = fileIndexByPath[q.get("file")];
  if (idx === undefined) { showOverview(); return; }
  selectFile(idx);
  const start = Number(q.get("start")), end = Number(q.get("end"));
  const first = $("reading").querySelector('.row[data-line="' + start + '"]');
  if (!first) return;
  for (const row of $("reading").querySelectorAll(".row")) {
    const n = Number(row.dataset.line);
    if (n >= start && n <= end) row.classList.add("target-line");
  }
  first.scrollIntoView({block:"center"});
}
