(function () {
  "use strict";

  var DATA = window.MCR_DATA;
  var state = {
    lang: localStorage.getItem("mcr.lang") || "zh",
    fontSize: parseFloat(localStorage.getItem("mcr.fontSize") || "14"),
    fileIndex: 0,
    serverAvailable: false,
    askContext: null,
    history: [],
    askSession: 0,
    busy: false,
    view: "reader",
    collapsed: Object.create(null)
  };

  var $ = function (id) { return document.getElementById(id); };

  var I18N = {
    zh: {
      askTitle: "代码解读",
      placeholder: "继续追问这段代码… (Enter 发送)",
      autoExplain: "解释这段代码",
      autoPrompt: "用 2-3 句话概括我选中代码的作用，再指出最关键的逻辑或坑。控制在 250 字以内，不要逐行罗列；我追问时再展开细节。",
      noServer: "当前为离线 HTML，未连接本地服务。\n要使用划词提问，请在项目目录运行：\n\npython -m mcr.serve <repo> --annotations <dir>\n\n并设置环境变量 MCR_API_KEY（OpenAI 兼容接口）。",
      thinking: "正在解读选中代码…", error: "请求失败：",
      sendError: "发送失败，请重试。",
      overview: "仓库总览", overviewCrumb: "仓库导读",
      annotatedStats: "{a} / {b} 个源文件附有双语讲解",
      noAnnotation: "该文件尚未生成注释，仅展示源代码。"
    },
    en: {
      askTitle: "Code Explainer",
      placeholder: "Ask a follow-up about this code… (Enter to send)",
      autoExplain: "Explain this code",
      autoPrompt: "Summarize what my selected code does in 2-3 sentences, then point out the most important logic or pitfall. Keep it under 150 words; don't go line by line — I'll ask follow-ups for details.",
      noServer: "This is an offline HTML file with no local server attached.\nTo enable code questions, run:\n\npython -m mcr.serve <repo> --annotations <dir>\n\nand set MCR_API_KEY (OpenAI-compatible API).",
      thinking: "Explaining the selection…", error: "Request failed: ",
      sendError: "Failed to send. Please retry.",
      overview: "Overview", overviewCrumb: "Repository guide",
      annotatedStats: "{a} of {b} source files have bilingual guides",
      noAnnotation: "No annotations for this file yet — showing source code only."
    }
  };
  function t(key) { return I18N[state.lang][key]; }

  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function renderMarkdownLite(text) {
    var esc = escapeHtml(text);
    esc = esc.replace(/```(\w*)\n?([\s\S]*?)```/g, function (_, lang, code) {
      return "<pre><code>" + code.replace(/^\n+|\n+$/g, "") + "</code></pre>";
    });
    esc = esc.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    esc = esc.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    esc = esc.replace(/^#{1,4}\s+(.+)$/gm, "<strong class=\"md-h\">$1</strong>");
    esc = esc.replace(/^[ \t]*[-*]\s+/gm, "• ");
    esc = esc.replace(/\n/g, "<br>");
    return esc;
  }

  // Highlight the whole file once, then split into per-line HTML while
  // re-balancing <span> tags that cross line boundaries (multi-line strings,
  // block comments, etc.), so each rendered line stays independently valid.
  function highlightLines(code, lang) {
    var html;
    try {
      html = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
    } catch (e) {
      html = escapeHtml(code);
    }
    var lines = [];
    var stack = [];
    var cur = "";
    var re = /(<span[^>]*>|<\/span>|\n|[^<\n]+|<)/g;
    var m;
    while ((m = re.exec(html)) !== null) {
      var tok = m[0];
      if (tok === "\n") {
        cur += new Array(stack.length + 1).join("</span>");
        lines.push(cur);
        cur = stack.join("");
      } else if (tok === "</span>") {
        stack.pop();
        cur += tok;
      } else if (tok.slice(0, 5) === "<span") {
        stack.push(tok);
        cur += tok;
      } else {
        cur += tok;
      }
    }
    lines.push(cur);
    return lines;
  }

  function applyFontSize() {
    document.documentElement.style.setProperty("--code-font-size", state.fontSize + "px");
    document.documentElement.style.setProperty("--exp-font-size", (state.fontSize + 0.5) + "px");
    localStorage.setItem("mcr.fontSize", String(state.fontSize));
  }

  var fileIndexByPath = Object.create(null);
  DATA.files.forEach(function (f, i) { fileIndexByPath[f.path] = i; });

  /*__MCR_GUIDE__*/

  function buildNested(paths) {
    var root = { dirs: Object.create(null), files: [] };
    paths.forEach(function (p) {
      var parts = p.split("/");
      var node = root;
      for (var i = 0; i < parts.length - 1; i++) {
        var d = parts[i];
        if (!node.dirs[d]) {
          node.dirs[d] = { dirs: Object.create(null), files: [], path: parts.slice(0, i + 1).join("/") };
        }
        node = node.dirs[d];
      }
      node.files.push(p);
    });
    return root;
  }

  // Keep build artifacts out of the initial explorer while exposing the learning path.
  const guidedDirs = new Set();
  function parents(path) {
    const parts = path.split("/");
    return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
  }
  DATA.files.filter(f => f.blocks.length).forEach(f => parents(f.path).forEach(p => guidedDirs.add(p)));
  (DATA.tree || []).forEach(path => parents(path).forEach(p => {
    if (!guidedDirs.has(p)) state.collapsed[p] = true;
  }));

  function renderTree() {
    var tree = $("file-tree");
    tree.innerHTML = "";
    $("repo-name").textContent = DATA.repo;
    var paths = (DATA.tree && DATA.tree.length) ? DATA.tree : DATA.files.map(function (f) { return f.path; });
    var nested = buildNested(paths);

    function walk(node, container, depth) {
      Object.keys(node.dirs).sort().forEach(function (name) {
        var d = node.dirs[name];
        var collapsed = !!state.collapsed[d.path];
        var row = document.createElement("button");
        row.className = "tree-dir";
        row.style.paddingLeft = (12 + depth * 14) + "px";
        var arrow = document.createElement("span");
        arrow.className = "arrow";
        arrow.textContent = collapsed ? "▸" : "▾";
        row.appendChild(arrow);
        row.appendChild(document.createTextNode(" " + name));
        row.setAttribute("aria-expanded", String(!collapsed));
        row.onclick = function () {
          if (collapsed) delete state.collapsed[d.path]; else state.collapsed[d.path] = true;
          renderTree();
        };
        container.appendChild(row);
        if (!collapsed) walk(d, container, depth + 1);
      });
      node.files.forEach(function (p) {
        var idx = fileIndexByPath[p];
        var f = idx !== undefined ? DATA.files[idx] : null;
        var btn = document.createElement("button");
        btn.className = "tree-file";
        if (state.view === "reader" && idx === state.fileIndex) btn.classList.add("active");
        if (idx === undefined) btn.classList.add("disabled");
        btn.style.paddingLeft = (26 + depth * 14) + "px";
        const base = p.split("/").pop();
        const ext = base.includes(".") ? base.split(".").pop().toLowerCase() : "";
        const icon = el("span", "file-icon");
        icon.dataset.ext = ext;
        icon.setAttribute("aria-hidden", "true");
        btn.append(icon, document.createTextNode(base));
        btn.title = p;
        if (f && f.blocks.length) {
          var dot = document.createElement("span");
          dot.className = "ann-dot";
          dot.title = state.lang === "zh" ? "已生成注释" : "Annotated";
          btn.appendChild(dot);
        }
        if (idx !== undefined) btn.onclick = function () { openPath(p); };
        container.appendChild(btn);
      });
    }
    walk(nested, tree, 0);
  }

  function navigate(hash) {
    if (hash !== location.hash) history.pushState(null, "", hash);
    followLocation();
  }

  // Resolve internal links during the click so the visible selection and URL
  // always agree. Modified clicks retain the browser's native tab behavior.
  document.addEventListener("click", function (event) {
    const a = event.target.closest("a[href^='#']");
    if (!a || event.button !== 0 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    event.preventDefault();
    navigate(a.hash);
  });

  function openPath(path) {
    const hash = "#" + new URLSearchParams({file:path});
    navigate(hash);
    if (matchMedia("(max-width: 900px)").matches) $("sidebar").classList.add("collapsed");
  }

  function selectFile(i) {
    parents(DATA.files[i].path).forEach(p => delete state.collapsed[p]);
    state.fileIndex = i;
    state.view = "reader";
    $("overview").classList.add("hidden");
    $("reading").classList.remove("hidden");
    renderTree();
    renderFile();
    $("content").scrollTop = 0;
  }

  function showOverview() {
    state.view = "overview";
    renderTree();
    $("reading").classList.add("hidden");
    $("file-note").classList.remove("visible");
    $("overview").classList.remove("hidden");
    $("crumb").textContent = t("overviewCrumb");
    renderOverview();
    $("content").scrollTop = 0;
  }

  function renderOverview() {
    var ov = $("overview");
    ov.innerHTML = "";
    var s = DATA.structure || {};
    var key = state.lang;
    var dirInfo = s.dirs || {};
    var fileInfo = s.files || {};
    var annotated = DATA.files.filter(function (f) { return f.blocks.length; }).length;

    var head = document.createElement("div");
    head.className = "ov-head";
    var title = document.createElement("h2");
    title.textContent = DATA.repo;
    head.appendChild(title);
    if (s["repo_" + key]) {
      var p = document.createElement("p");
      p.className = "ov-summary";
      p.innerHTML = renderMarkdownLite(s["repo_" + key]);
      head.appendChild(p);
    }
    var stats = document.createElement("div");
    stats.className = "ov-stats";
    stats.textContent = t("annotatedStats").replace("{a}", annotated).replace("{b}", DATA.files.length);
    head.appendChild(stats);
    ov.appendChild(head);
    renderTutorial(ov);

    var paths = (DATA.tree && DATA.tree.length) ? DATA.tree : DATA.files.map(function (f) { return f.path; });
    var nested = buildNested(paths);
    var list = document.createElement("div");
    list.className = "ov-tree";

    function walk(node, depth) {
      Object.keys(node.dirs).sort().forEach(function (name) {
        var d = node.dirs[name];
        var row = document.createElement("div");
        row.className = "ov-row ov-dir";
        row.style.paddingLeft = (depth * 22) + "px";
        var nm = document.createElement("span");
        nm.className = "ov-name";
        nm.textContent = name + "/";
        row.appendChild(nm);
        var info = dirInfo[d.path];
        if (info && info[key]) {
          var desc = document.createElement("span");
          desc.className = "ov-desc";
          desc.innerHTML = renderMarkdownLite(info[key]);
          row.appendChild(desc);
        }
        list.appendChild(row);
        walk(d, depth + 1);
      });
      node.files.forEach(function (p) {
        var idx = fileIndexByPath[p];
        var row = document.createElement("div");
        row.className = "ov-row ov-file" + (idx !== undefined ? " clickable" : "");
        row.style.paddingLeft = (depth * 22 + 18) + "px";
        var nm = document.createElement("span");
        nm.className = "ov-name";
        nm.textContent = p.split("/").pop();
        if (idx !== undefined && DATA.files[idx].blocks.length) nm.classList.add("annotated");
        row.appendChild(nm);
        var info = fileInfo[p];
        if (info && info[key]) {
          var desc = document.createElement("span");
          desc.className = "ov-desc";
          desc.innerHTML = renderMarkdownLite(info[key]);
          row.appendChild(desc);
        }
        if (idx !== undefined) {
          row.title = p;
          row.onclick = function () { openPath(p); };
        }
        list.appendChild(row);
      });
    }
    walk(nested, 0);
    const index = el("details", "file-index");
    index.open = !chapters.length;
    index.append(el("summary", "", caption("目录与文件职责", "Directory and file guide")), list);
    ov.append(index);
  }

  function renderFile() {
    var f = DATA.files[state.fileIndex];
    if (!f) { $("reading").innerHTML = ""; return; }
    $("crumb").replaceChildren();
    if (chapters.length && params().has("chapter")) {
      $("crumb").append(chapterLink(currentChapter(), currentChapter().title[state.lang]), "  ›  ");
    }
    $("crumb").append(f.path + "  ·  " + f.language);
    var note = $("file-note");
    var isRaw = !f.blocks.length;
    renderFileIntro(f, note);

    var rawLines = f.code.replace(/\t/g, "    ").split("\n");
    var codeLines = highlightLines(f.code.replace(/\t/g, "    "), f.language);
    var reading = $("reading");
    reading.innerHTML = "";
    reading.classList.toggle("raw", isRaw);
    var key = state.lang;

    var blocks = isRaw
      ? [{ start: 1, end: rawLines.length - (rawLines[rawLines.length - 1] === "" ? 1 : 0), lines: [] }]
      : f.blocks;
    blocks.forEach(function (b) {
      if (b.end < b.start) return;
      var block = document.createElement("div");
      block.className = "block";

      var header = document.createElement("div");
      header.className = "block-header";
      if (isRaw) header.style.display = "none";
      var range = document.createElement("span");
      range.className = "range";
      range.textContent = "L" + b.start + "–" + b.end;
      var summary = document.createElement("span");
      summary.className = "summary";
      summary.innerHTML = b["summary_" + key] ? renderMarkdownLite(b["summary_" + key]) : "";
      header.appendChild(range);
      header.appendChild(summary);
      header.onclick = function () { block.classList.toggle("focused"); };
      block.appendChild(header);

      var expByLine = {};
      (b.lines || []).forEach(function (ln) { expByLine[ln.n] = ln; });

      for (var n = b.start; n <= b.end; n++) {
        var row = document.createElement("div");
        row.className = "row";
        row.dataset.line = n;
        var codeCell = document.createElement("div");
        codeCell.className = "code-cell";
        var lineno = document.createElement("span");
        lineno.className = "lineno";
        lineno.textContent = n;
        var code = document.createElement("code");
        code.className = "code hljs";
        var idx = n - 1;
        code.innerHTML = (idx < codeLines.length && codeLines[idx]) || " ";
        codeCell.appendChild(lineno);
        codeCell.appendChild(code);

        var expCell = document.createElement("div");
        expCell.className = "exp-cell";
        const explanation = expByLine[n];
        if (explanation) {
          if (explanation.end > n) {
            expCell.append(evidence(f.path, n, explanation.end, "L" + n + "–" + explanation.end));
          }
          const words = el("span");
          words.innerHTML = renderMarkdownLite(explanation[key]);
          expCell.append(words);
        }

        row.appendChild(codeCell);
        row.appendChild(expCell);
        row.onclick = function () {
          var wasPinned = document.querySelector(".row.pinned");
          if (wasPinned) wasPinned.classList.remove("pinned");
          if (wasPinned !== this) this.classList.add("pinned");
        };
        block.appendChild(row);
      }
      reading.appendChild(block);
    });
  }

  function applyLang() {
    localStorage.setItem("mcr.lang", state.lang);
    document.documentElement.lang = state.lang === "zh" ? "zh" : "en";
    $("lang-toggle").textContent = state.lang === "zh" ? "EN" : "中";
    document.querySelector("#ask-panel .ask-title").textContent = t("askTitle");
    $("ask-input").placeholder = t("placeholder");
    $("overview-label").textContent = t("overview");
    if (state.view === "overview") {
      $("crumb").textContent = t("overviewCrumb");
      renderOverview();
    } else {
      followLocation();
    }
  }

  // ---------- selection → instant AI explanation ----------

  document.addEventListener("mouseup", function (e) {
    if ($("ask-panel").contains(e.target)) return;
    setTimeout(function () {
      var sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.toString().trim()) return;
      var anchor = sel.anchorNode;
      if (!anchor) return;
      var el = anchor.nodeType === 3 ? anchor.parentElement : anchor;
      var codeCell = el.closest ? el.closest(".code-cell") : null;
      if (!codeCell) return;

      var f = DATA.files[state.fileIndex];
      var startRow = codeCell.closest(".row");
      var focusEl = sel.focusNode && sel.focusNode.nodeType === 3
        ? sel.focusNode.parentElement : sel.focusNode;
      var endCell = focusEl && focusEl.closest ? focusEl.closest(".code-cell") : null;
      var endRow = endCell ? endCell.closest(".row") : startRow;
      var l1 = startRow ? parseInt(startRow.dataset.line, 10) : null;
      var l2 = endRow ? parseInt(endRow.dataset.line, 10) : l1;
      var text = sel.toString();
      if (l1 && l2 && l1 !== l2) {
        // A cross-row DOM selection also captures the right-pane explanation
        // cells. Rebuild the snippet from the actual source lines instead.
        var lo = Math.min(l1, l2), hi = Math.max(l1, l2);
        text = f.code.split("\n").slice(lo - 1, hi).join("\n");
      }
      if (text.length > 8000) text = text.slice(0, 8000);
      state.askContext = {
        file: f.path,
        language: f.language,
        selection: text,
        line: l1 && l2 ? Math.min(l1, l2) : l1,
        lineEnd: l1 && l2 ? Math.max(l1, l2) : l2
      };
      openAsk();
      if (state.serverAvailable) {
        askModel(t("autoExplain"), t("autoPrompt"));
      }
    }, 10);
  });

  function openAsk() {
    state.askSession++;
    state.busy = false;
    $("ask-send").disabled = false;
    $("ask-panel").classList.remove("hidden");
    var ctx = state.askContext;
    var ctxEl = $("ask-context");
    if (ctx) {
      var range = ctx.line ? (ctx.lineEnd && ctx.lineEnd !== ctx.line
        ? " · L" + ctx.line + "–" + ctx.lineEnd : " · L" + ctx.line) : "";
      ctxEl.textContent = ctx.file + range + "\n" +
        (ctx.selection.length > 600 ? ctx.selection.slice(0, 600) + " …" : ctx.selection);
      ctxEl.classList.remove("hidden");
    } else {
      ctxEl.classList.add("hidden");
    }
    $("ask-messages").innerHTML = "";
    state.history = [];
    if (!state.serverAvailable) {
      addMessage("ai", t("noServer"), true);
    }
  }

  function addMessage(role, text, raw) {
    var wrap = $("ask-messages");
    var div = document.createElement("div");
    div.className = "msg " + role;
    var label = document.createElement("div");
    label.className = "role";
    label.textContent = role === "user" ? (state.lang === "zh" ? "你" : "You") : "AI";
    var body = document.createElement("div");
    body.className = "body";
    if (raw) body.textContent = text; else body.innerHTML = renderMarkdownLite(text);
    div.appendChild(label);
    div.appendChild(body);
    wrap.appendChild(div);
    wrap.scrollTop = wrap.scrollHeight;
    return body;
  }

  function askModel(displayQuestion, prompt) {
    if (state.busy) return;
    state.busy = true;
    var session = state.askSession;
    addMessage("user", displayQuestion, true);
    var aiBody = addMessage("ai", t("thinking"), true);
    aiBody.classList.add("thinking");
    $("ask-send").disabled = true;
    var ctx = state.askContext || {};

    function scrollBottom() { $("ask-messages").scrollTop = $("ask-messages").scrollHeight; }

    fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        file: ctx.file || "",
        language: ctx.language || "",
        selection: ctx.selection || "",
        line: ctx.line || null,
        line_end: ctx.lineEnd || null,
        question: prompt,
        lang: state.lang,
        history: state.history
      })
    }).then(function (r) {
      var ctype = r.headers.get("Content-Type") || "";
      if (!r.ok || ctype.indexOf("text/plain") === -1 || !r.body) {
        return r.json().then(function (data) {
          throw new Error(data.error || ("HTTP " + r.status));
        });
      }
      // Streamed plain-text answer: render tokens as they arrive.
      var reader = r.body.getReader();
      var decoder = new TextDecoder();
      var acc = "";
      var started = false;
      function pump() {
        return reader.read().then(function (res) {
          if (session !== state.askSession) { reader.cancel(); return null; }
          if (res.done) {
            state.history.push({ role: "user", content: prompt });
            state.history.push({ role: "assistant", content: acc });
            return null;
          }
          acc += decoder.decode(res.value, { stream: true });
          if (!started && acc.trim()) {
            started = true;
            aiBody.classList.remove("thinking");
          }
          if (started) {
            aiBody.innerHTML = renderMarkdownLite(acc);
            scrollBottom();
          }
          return pump();
        });
      }
      return pump();
    }).catch(function (err) {
      if (session !== state.askSession) return;
      aiBody.classList.remove("thinking");
      aiBody.textContent = t("error") + err.message;
    }).finally(function () {
      if (session !== state.askSession) return;
      state.busy = false;
      $("ask-send").disabled = false;
      $("ask-input").focus();
      scrollBottom();
    });
  }

  function sendQuestion() {
    var input = $("ask-input");
    var q = input.value.trim();
    if (!q || !state.serverAvailable || state.busy) return;
    input.value = "";
    askModel(q, q);
  }

  function checkServer() {
    if (location.protocol === "file:") return;
    fetch("/api/health").then(function (r) { return r.json(); }).then(function (d) {
      state.serverAvailable = !!(d && d.ok && d.llm);
    }).catch(function () { state.serverAvailable = false; });
  }

  // ---------- wire up ----------

  $("sidebar-toggle").onclick = function () { $("sidebar").classList.toggle("collapsed"); };
  $("overview-btn").onclick = function () {
    navigate("#overview");
    if (matchMedia("(max-width: 900px)").matches) $("sidebar").classList.add("collapsed");
  };
  window.addEventListener("hashchange", followLocation);
  $("lang-toggle").onclick = function () {
    state.lang = state.lang === "zh" ? "en" : "zh";
    applyLang();
  };
  $("font-dec").onclick = function () { state.fontSize = Math.max(10, state.fontSize - 1); applyFontSize(); };
  $("font-inc").onclick = function () { state.fontSize = Math.min(22, state.fontSize + 1); applyFontSize(); };
  $("ask-close").onclick = function () {
    state.askSession++;
    state.busy = false;
    $("ask-panel").classList.add("hidden");
  };
  $("ask-send").onclick = sendQuestion;
  $("ask-input").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      sendQuestion();
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      state.askSession++;
      state.busy = false;
      $("ask-panel").classList.add("hidden");
    }
  });

  applyFontSize();
  if (matchMedia("(max-width: 900px)").matches) $("sidebar").classList.add("collapsed");
  state.view = "overview";
  applyLang();
  followLocation();
  checkServer();
})();
