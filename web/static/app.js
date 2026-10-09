var DATA = null, DAYS = [], BK = [], state = null;
var ACTS = [], AID = null;                      // 活动清单 + 当前看的活动（服务版才有）
var LS_KEY = "ad_dashboard_activity";           // 记住上次看的是哪个活动
var FRESH = null, FRESH_KEY = "";               // 数据新鲜度（服务版：最近取数 / 自动刷新）
var TODO = null;                                // 待复盘清单（/api/todo，**跨活动**；2026-09-30 加）
function boot(data, keep){
  DATA = data;
  DAYS = data.days || [];
  BK = data.buckets || [];
  document.title = "投放看板 · " + (data.label || "");
  var v = { open:null, mode:"bucket", exp:{}, bs: BK.length ? BK[0].id : null };
  if(keep){                                  // 刷新后保住用户选的桶/口径（2026-10-08 起没有"所选批次"了）
    if(keep.bs && bById(keep.bs)) v.bs = keep.bs;
    if(keep.mode) v.mode = keep.mode;
  }
  state = { open: v.open, mode: v.mode, exp: v.exp, bs: v.bs,
            mstyle: "auto", mctx: null };
  renderAll();
}
function $(id){ return document.getElementById(id); }
function bById(id){ for(var i=0;i<BK.length;i++){ if(BK[i].id===id) return BK[i]; } return null; }
// 一个桶"当天的量"和"哪些天算有量"，口径都在 payload 里算好了（perf_payload）——
function fmt(n){ return Math.round(n).toLocaleString("en-US"); }
function pct(c, e){ return e ? (c/e*100).toFixed(2)+"%" : "—"; }
function dayTotal(){                           // 全活动最新一天（今天）合计——放页头那一行
  var day = DAYS.length ? DAYS[DAYS.length - 1] : null;
  if(!day) return null;
  var e = 0, c = 0;
  (DATA.orders || []).forEach(function(o){
    var v = ((DATA.orderCells || {})[o.name] || {})[day];
    if(v){ e += v[0]; c += v[1]; }
  });
  return {day: day, e: e, c: c};
}
function renderHead(){
  var last = DAYS.length ? DAYS[DAYS.length-1] : "—";
  $("ttl").textContent = DATA.label;
  $("snaptag").textContent = "数据至 " + last;
  var bits = ["数据区间 " + DAYS[0] + " ~ " + last + "（" + DAYS.length + " 天）"];
  var d = dayTotal();
  if(d) bits.push("今日（" + d.day.slice(5) + "）曝光 " + fmt(d.e) + " · 点击 " + fmt(d.c));
  if(FRESH){
    bits.push(FRESH.lastFetchTime ? ("最近取数 " + FRESH.lastFetchTime) : "还没取过数");
    if(FRESH.auto && FRESH.auto.minutes){
      bits.push("自动刷新 每 " + FRESH.auto.minutes + " 分钟" +
                (FRESH.auto.at ? ("（上次 " + FRESH.auto.at + (FRESH.auto.ok === false ? " 失败" : "") + "）") : ""));
    }else if(FRESH.auto){
      bits.push("自动刷新 已关");
    }
  }
  $("subline").innerHTML = bits.join(" ｜ ");
}

function freshTick(){                            // 服务版：60 秒问一次"数据是不是被自动刷新更新了"
  if(window.__DATA__ || !AID) return;
  fetch("api/fetch/status" + actQuery(), { cache:"no-store" }).then(function(r){ return r.json(); }).then(function(st){
    var key = [(st.db || {}).last, st.lastFetchTime, (st.auto || {}).at, st.running].join("|");
    var changed = FRESH_KEY && key !== FRESH_KEY;
    FRESH_KEY = key;
    FRESH = {lastFetchTime: st.lastFetchTime || "", auto: st.auto || null};
    if(DATA) renderHead();
    if(changed && !st.running){                // 自动刷新跑完 → 顺手更新页面 **和角标**
      // 2026-10-09 修：以前只换表格、不重问待复盘清单，角标会停在自动刷新开始前那一刻的数字
      // （表格里三条"过门槛 · 未达标"，角标却显示 1）。
      loadFromServer(state ? currentView() : null);
      loadTodo();
    }
  }).catch(function(){});
}

// ---- 分桶统计（2026-10-08 改）：一行 = 一个桶**最新那个任务**，各桶有自己的当前批 ----
// 判定规则在 automation/scripts/judging.py（命令行 judge_batch 和这里共用一份），页面只负责画。
// 桶维度（当前批 / 回退批 / 批次史）在 perf_payload.bucket_view() 里算好，页面不再自己推。
function batchById(id){
  var bs = DATA.batches || [];
  for(var i=0;i<bs.length;i++){ if(bs[i].id === id) return bs[i]; }
  return null;
}
function copyOf(res){ return (DATA.copy || {})[res] || null; }      // 资源名 → 文案原文
function plain(s){ return String(s == null ? "" : s).replace(/\*\*/g, ""); }
function taskOf(bk){                                               // 该桶「最新那个任务」= 它自己当前批那一行
  if(!bk) return null;
  var list = bk.batches || [];
  for(var i=0;i<list.length;i++){ if(list[i].batch === bk.currentBatch) return list[i]; }
  return list.length ? list[list.length-1] : null;
}
function hl(text, word){                       // 飘红：直接把词标在文案里（不再单起一行）
  var s = esc(text == null ? "" : text);
  if(!word) return s;
  var w = esc(word);
  var re = new RegExp(w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g");
  return s.replace(re, '<span class="hl">' + w + '</span>');
}
function slotName(res){                         // `…A类 · 对照-4` → `对照`
  return String(res || "").split(" · ").pop().replace(/-\d+$/, "");
}
function slotNames(list){                       // 按槽位顺序排列（别按点击数，读起来才顺）
  var order = ["对照", "实验1", "实验2"];
  return (list || []).map(slotName).sort(function(a, b){
    var ia = order.indexOf(a), ib = order.indexOf(b);
    return (ia < 0 ? 9 : ia) - (ib < 0 ? 9 : ib);
  }).join("、");
}
function topicOf(j){                            // 工单名里的受众人群：`…-A类 · AI 编程 / Agent 工具-6` → 中间那段
  if(!j || !j.task) return "";
  var parts = String(j.task).split(" · ");
  return parts.length > 1 ? parts[1].replace(/-\d+$/, "") : "";
}
function renderBuckets(){                      // 主表：一行 = 一个桶**最新那个任务**（各桶批次可以不同）
  var box = $("buckets");
  if(!box) return;
  var hasTh = !!DATA.thresholds && Object.keys(DATA.thresholds).length > 0;
  var h = '<table><colgroup><col style="width:17%"><col style="width:22%"><col style="width:10%">' +
          '<col style="width:11%"><col style="width:12%"><col style="width:28%"></colgroup>' +
          '<thead><tr><th>桶</th><th class="c">' + (hasTh ? "曝光 / 门槛" : "曝光") +
          '</th><th class="n">点击</th><th class="n">点击率</th><th>判定</th>' +
          '<th>文案 / 动作</th></tr></thead><tbody>';
  BK.forEach(function(bk){
    var j = taskOf(bk);
    if(!j) return;
    var th = (bk.threshold != null) ? bk.threshold : j.threshold;
    var e = j.exposure || 0, c = j.click || 0;
    var p = th ? Math.min(100, e / th * 100) : 0;
    var badge = !hasTh ? '<span class="badge dim">—</span>'
              : (!j.task ? '<span class="badge dim">待起投</span>'
              : (j.pass ? '<span class="badge ok">达标</span>'
              : (j.ready ? '<span class="badge warn">过门槛 · 未达标</span>'
                         : '<span class="badge dim">未到门槛</span>')));
    var act = '<span class="badge dim">—</span>';
    if(j.action){                               // 调整过 → 写**调整动作**（人定的，`配置/复盘动作.yaml`）
      act = '<span class="badge hi">调整动作</span> 留 ' + ((j.action.keep || []).join("、") || "—") +
            ' ｜ 下 ' + ((j.action.drop || []).join("、") || "—");
      if(j.action.note) act += ideaBtn(j.batch, bk.id);   // 调整思路收进图标弹窗（2026-09-30 用户定）
    } else if(hasTh && j.ready){                // 没调整 → 写**建议动作**（规则算的）
      act = '<span class="badge dim">建议动作</span> <b class="actkeep">留 ' +
            (slotNames(j.keep) || "—") + '</b> ｜ <span class="actdrop">下 ' +
            (slotNames(j.drop) || "—") + '</span>';
    } else if(hasTh){                            // 没调整 + 还没到门槛 → 建议也是**继续观察**（不写“—”）
      act = '<span class="badge dim">建议动作</span> ' + esc(j.conclusion || "继续观察");
    }
    h += '<tr class="mainrow" data-cmp="' + bk.id + '|' + esc(j.batch) + '" title="看三条文案的对比">' +
         '<td><span class="mkdot" style="background:' + bk.color + '">' + bk.id + '</span> ' +
           esc(bk.topic || ("桶 " + bk.id)) + '</td>' +
         '<td class="c" style="white-space:nowrap">' +
           (th ? '<span class="barwrap" style="width:100px"><span class="bar" style="width:' +
             p.toFixed(1) + '%;background:' + bk.color + '"></span></span> <span class="num">' + fmt(e) +
             ' / ' + fmt(th) + '</span>' : '<span class="num">' + fmt(e) + '</span>') + '</td>' +
         '<td class="n num">' + fmt(c) + '</td>' +
         '<td class="n num">' + pct(c, e) + '</td>' +
         '<td>' + badge + '</td><td>' + act + '</td></tr>';
  });
  box.innerHTML = h + '</tbody></table>';
}

// ---- 批次之间（2026-09-28）：图随「桶级 / 资源级」切；表格恒为一批一行，点行展开（可多开）----
var SLOT_COLORS = ["#8B5CF6", "#2563EB", "#14B8A6"];   // 对照 / 实验1 / 实验2（紫 / 蓝 / 青）
var SLOT_ORDER = {"对照组": 0, "实验组1": 1, "实验组2": 2};
function groupsBySlot(gs){                     // 槽位固定顺序（对照→实验1→实验2），颜色永远对得上
  return (gs || []).slice().sort(function(a, b){
    var ia = SLOT_ORDER[a.label] == null ? 9 : SLOT_ORDER[a.label];
    var ib = SLOT_ORDER[b.label] == null ? 9 : SLOT_ORDER[b.label];
    return ia - ib;
  });
}
function seriesOf(bid){                        // 该桶的批次史（payload 算好的），**最新 → 最老**
  var bk = bById(bid);
  if(!bk) return [];
  return (bk.batches || []).map(function(x){
    return {label: x.label, batch: x.batch, start: x.start, cur: x.batch === bk.currentBatch,
            e: x.exposure || 0, c: x.click || 0, groups: groupsBySlot(x.groups || [])};
  }).filter(function(s){ return s.e || s.c || s.groups.length; }).reverse();
}
function renderBatchStats(){
  var box = $("batchstats");
  if(!box) return;
  var mc = $("ctlmode");
  if(mc) mc.innerHTML = [["bucket","桶级"],["copy","资源级"]].map(function(m){
    return '<button class="fbtn'+(state.mode === m[0] ? " on" : "")+'" data-mode="'+m[0]+'">'+m[1]+'</button>';
  }).join("");
  var ctl = $("ctlbs");
  if(ctl) ctl.innerHTML = BK.map(function(b){
    return '<button class="fbtn'+(state.bs === b.id ? " on" : "")+'" data-bs="'+b.id+'">'+b.id+'</button>';
  }).join("");
  var bk = bById(state.bs);
  var series = seriesOf(state.bs);
  if(!bk || !series.length){ box.innerHTML = '<p class="hint">这个桶还没有可比的批次。</p>'; return; }
  box.innerHTML = batchChart(series, bk) + batchTable(series, bk);
}
function niceMax(v){                           // 纵轴取整（1/2/5 × 10^k 往上找），刻度别出现 3.67 这种
  if(v <= 4) return Math.max(1, Math.ceil(v));
  var p = Math.pow(10, Math.floor(Math.log(v) / Math.LN10)), f = v / p;
  var m = f <= 1 ? 1 : (f <= 2 ? 2 : (f <= 5 ? 5 : 10));
  return m * p;
}
function batchChart(series, bk){               // 柱 = 点击；柱顶留空放数字；x 轴：槽位 / 批次 / 曝光
  var copyMode = state.mode === "copy";
  var W = 980, H = 226, x0 = 64, x1 = 930, yb = 152, yt = 30, top = 16;
  var n = Math.max(series.length, 1), gw = (x1 - x0) / n;
  var maxV = 0;
  series.forEach(function(s){
    if(copyMode) s.groups.forEach(function(g){ maxV = Math.max(maxV, g.c); });
    else maxV = Math.max(maxV, s.c);
  });
  var axis = niceMax(maxV);
  var s2 = ['<svg viewBox="0 0 '+W+' '+H+'" width="100%" height="'+H+'" role="img" aria-label="'+
            bk.id+' 桶各批次点击">'];
  s2.push('<line x1="'+x0+'" y1="'+yb+'" x2="'+x1+'" y2="'+yb+'" stroke="#E2E8F0"/>');
  for(var i = 1; i <= 3; i++){
    var y = yb - (yb - yt - top) * i / 3;
    s2.push('<line x1="'+x0+'" y1="'+y.toFixed(1)+'" x2="'+x1+'" y2="'+y.toFixed(1)+'" stroke="#F1F5F9"/>');
    s2.push('<text x="'+(x0-10)+'" y="'+(y+3.5).toFixed(1)+'" text-anchor="end" font-size="10.5" fill="#94A3B8">'+
            fmt(axis*i/3)+'</text>');
  }
  s2.push('<text x="'+(x0-10)+'" y="'+(yb+3.5)+'" text-anchor="end" font-size="10.5" fill="#94A3B8">0</text>');
  var bw = copyMode ? Math.min(24, gw*0.72/4) : Math.min(46, Math.max(22, gw*0.42));
  series.forEach(function(st, i){
    var gx = x0 + gw*(i + 0.5);
    var bars = copyMode ? st.groups.map(function(g, k){ return {g: g, k: k}; }) : [{g: null, k: 0}];
    var gap = 6, full = bars.length*bw + (bars.length-1)*gap, left = gx - full/2;
    bars.forEach(function(bd, k){
      var v = bd.g ? bd.g.c : st.c;
      var hgt = axis ? (yb - yt - top) * Math.min(1, v/axis) : 0;
      var x = left + k*(bw+gap);
      var col = copyMode ? SLOT_COLORS[bd.k % 3] : (st.cur ? "#1D4ED8" : "#60A5FA");
      s2.push('<rect x="'+x.toFixed(1)+'" y="'+(yb-hgt).toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+
              Math.max(1.5, hgt).toFixed(1)+'" rx="3" fill="'+col+'"><title>'+esc(st.label)+' '+
              esc((bd.g && bd.g.label) || (bk.id+" 桶"))+'：点击 '+fmt(v)+' / 曝光 '+
              fmt(bd.g ? bd.g.e : st.e)+'</title></rect>');
      if(v) s2.push('<text x="'+(x+bw/2).toFixed(1)+'" y="'+(yb-hgt-6).toFixed(1)+'" text-anchor="middle" '+
                    'font-size="10.5" fill="#475569">'+fmt(v)+'</text>');
      if(copyMode) s2.push('<text x="'+(x+bw/2).toFixed(1)+'" y="'+(yb+14)+'" text-anchor="middle" '+
                           'font-size="10" fill="#94A3B8">'+esc(((bd.g && bd.g.label) || "").replace("组",""))+'</text>');
    });
    s2.push('<text x="'+gx.toFixed(1)+'" y="'+(yb + (copyMode ? 31 : 18))+'" text-anchor="middle" '+
            'font-size="11.5" fill="'+(st.cur ? "#1E293B" : "#64748B")+'">'+esc(st.label)+'</text>');
    s2.push('<text x="'+gx.toFixed(1)+'" y="'+(yb + (copyMode ? 46 : 33))+'" text-anchor="middle" '+
            'font-size="10" fill="#B6C0CE">'+fmt(st.e)+' 曝光</text>');
  });
  s2.push('</svg>');
  return s2.join("");
}
function batchTable(series, bk){
  var maxC = 1;
  series.forEach(function(s){ maxC = Math.max(maxC, s.c); });
  var h = '<table style="table-layout:fixed"><colgroup><col style="width:30%"><col style="width:16%">' +
          '<col style="width:26%"><col style="width:28%"></colgroup><thead><tr><th>批次</th><th>起投</th>' +
          '<th class="n">曝光</th><th class="n">点击</th></tr></thead><tbody>';
  series.forEach(function(st){
    var key = st.batch === null ? "未归类" : st.batch;
    var open = !!state.exp[key];
    h += '<tr class="brow' + (st.cur ? " cur" : "") + '" data-bexp="' + key + '" style="cursor:pointer">' +
         '<td>' + esc(st.label) + (st.cur ? ' <span class="badge hi">当前批</span>' : '') +
         '</td><td>' + (st.start || "—") + '</td><td class="n num">' + fmt(st.e) +
         '</td><td class="n num">' + fmt(st.c) + ' <span class="barwrap" style="width:70px"><span class="bar" ' +
         'style="width:' + (st.c/maxC*100).toFixed(1) + '%;background:' + bk.color + '"></span></span>' +
         '</td></tr>';
    if(!open) return;
    st.groups.forEach(function(g, k){
      h += '<tr class="crow click"' + (st.batch ? ' data-cmp="' + bk.id + '|' + esc(st.batch) + '"' : '') +
           ' title="看三条文案的对比"><td><span class="slotdot" style="background:' + SLOT_COLORS[k % 3] + '"></span>' +
           esc(g.label || g.res) + '<div class="hint">' + esc(g.title || g.res) + '</div></td>' +
           '<td></td><td class="n num">' + fmt(g.e) + '</td><td class="n num">' + fmt(g.c) + '</td></tr>';
    });
  });
  return h + '</tbody></table>';
}

// ---- 三条文案对比大弹窗（2026-10-08）：**未到门槛看记分卡、过门槛看胜出特写** ----
// 结构（用户 2026-10-08 定）：标题/摘要在前、指标在下；保留走青、下走红；两条资源时自动两列。
var MSTYLES = [["auto", "自动"], ["score", "① 记分卡"], ["hero", "② 胜出特写"]];
function ctrOf(g){ return (g.e || 0) ? (g.c || 0) / g.e : 0; }   // 点击率（桶内比较用）
function betterOf(g, h){                        // g 比 h 好吗？大卡排序：点击率 → 点击 → 曝光
  if(!h) return true;
  if(ctrOf(g) !== ctrOf(h)) return ctrOf(g) > ctrOf(h);
  if((g.c || 0) !== (h.c || 0)) return (g.c || 0) > (h.c || 0);
  return (g.e || 0) > (h.e || 0);
}
function mctxOf(bk, j){
  var gs = groupsBySlot(j.groups || []);
  var th = (bk.threshold != null) ? bk.threshold : j.threshold;
  var e = j.exposure || 0;
  var maxE = 1, best = null;
  gs.forEach(function(g){
    maxE = Math.max(maxE, g.e || 0);
    if(!best || (g.c || 0) > (best.c || 0)) best = g;
  });
  var keep = gs.filter(function(g){ return g.keep; });
  // 大卡（胜出特写）= **保留名单里点击率最高的那条**（2026-10-09 用户定：大卡本来就该是"胜出"的，
  // 不能再按槽位取第一条——之前永远是"对照组"占大卡，点击最多的反而排到最后一行）。
  // 只在**保留**里挑：被"下"的那条放大卡，页面会自己打自己（大卡挂着红标"下"）。
  var top = keep.reduce(function(acc, g){ return betterOf(g, acc) ? g : acc; }, null);
  var ready = !!th && e >= th;
  return {gs: gs, th: th, e: e, ready: ready, pass: !!j.pass, maxE: maxE, best: best, keep: keep,
          hero: top || best || gs[0], bk: bk, j: j,
          act: th ? (ready
            ? '建议：<b class="actkeep">留 ' + (slotNames(j.keep) || "—") +
              '</b> ｜ <span class="actdrop">下 ' + (slotNames(j.drop) || "—") + '</span>'
            : '建议：继续观察') : '建议：无门槛'};
}
function markOf(g, c){
  if(!c.th) return '<span class="badge dim">—</span>';
  if(!c.ready) return '<span class="badge dim">等到达门槛</span>';
  return g.keep ? '<span class="badge keepflag">保留</span>' : '<span class="badge zero">下</span>';
}
function bestTag(g, c){ return (g === c.best && c.best.c > 0) ? '<span class="badge best">点击最高</span>' : ''; }
function slotOf(g, c){ return SLOT_COLORS[(c.gs.indexOf(g) + SLOT_COLORS.length) % SLOT_COLORS.length]; }
function titleOf(g){ return g.title ? hl(g.title, g.highlight) : esc(g.res || ""); }
function sumOf(g){ return g.summary ? hl(g.summary, g.highlight) : ""; }

function bodyScore(c){                          // ① 记分卡：标题/摘要在前，指标在后
  function row(label, fn, cls){
    return '<tr class="' + (cls || "") + '"><th class="rh">' + label + '</th>' + c.gs.map(fn).join("") + '</tr>';
  }
  return '<table class="scoretab"><thead><tr><th class="rh"></th>' + c.gs.map(function(g){
      return '<th class="' + (g === c.best ? "win" : "") + '"><span class="slotdot" style="background:' +
             slotOf(g, c) + '"></span>' + esc(g.label || "") + bestTag(g, c) + '</th>';
    }).join("") + '</tr></thead><tbody>' +
    row('标题', function(g){ return '<td>' + titleOf(g) + '</td>'; }, 'crowtitle') +
    row('摘要', function(g){ return '<td>' + sumOf(g) + '</td>'; }, 'crowsum') +
    row('曝光', function(g){
      return '<td><span class="num">' + fmt(g.e || 0) + '</span><i class="scorebar"><em style="width:' +
             ((g.e || 0) / c.maxE * 100).toFixed(1) + '%;background:' + slotOf(g, c) + '"></em></i></td>';
    }) +
    row('点击', function(g){ return '<td class="num">' + fmt(g.c || 0) + '</td>'; }) +
    row('点击率', function(g){ return '<td class="num">' + pct(g.c || 0, g.e || 0) + '</td>'; }) +
    row('判定', function(g){ return '<td>' + markOf(g, c) + '</td>'; }) +
    '</tbody></table>';
}
function bodyHero(c){                           // ② 胜出特写：左大卡 + 右两条小卡
  var hg = c.hero;
  var others = c.gs.filter(function(g){ return g !== hg; });
  return '<div class="hero">' +
    '<article class="herocard" style="--slot:' + slotOf(hg, c) + '">' +
      '<div class="cmpslot"><span class="slotdot" style="background:' + slotOf(hg, c) + '"></span>' +
        '<b>' + esc(hg.label || "") + '</b>' + bestTag(hg, c) +
        '<span class="badge keepflag">★ ' + (hg.keep ? '优先保留' : '点击最高') + '</span></div>' +
      '<h4 class="herocopy">' + titleOf(hg) + '</h4>' +
      '<p class="herosum">' + sumOf(hg) + '</p>' +
      '<div class="herostats">' +
        '<div><span>曝光</span><b class="num">' + fmt(hg.e || 0) + '</b></div>' +
        '<div><span>点击</span><b class="num">' + fmt(hg.c || 0) + '</b></div>' +
        '<div><span>点击率</span><b class="num">' + pct(hg.c || 0, hg.e || 0) + '</b></div>' +
      '</div></article>' +
    '<div class="runlist">' + others.map(function(g){
      return '<article class="runitem">' +
        '<div class="cmpslot"><span class="slotdot" style="background:' + slotOf(g, c) + '"></span>' +
          '<b>' + esc(g.label || "") + '</b>' + bestTag(g, c) + markOf(g, c) + '</div>' +
        '<div class="rcopy">' + titleOf(g) + '</div>' +
        '<div class="rsum">' + sumOf(g) + '</div>' +
        '<div class="runstats"><span>曝光 <b class="num">' + fmt(g.e || 0) + '</b></span>' +
          '<span>点击 <b class="num">' + fmt(g.c || 0) + '</b></span>' +
          '<span>点击率 <b class="num">' + pct(g.c || 0, g.e || 0) + '</b></span></div></article>';
    }).join("") + '</div></div>';
}
function openCompare(bid, batchId){
  var bk = bById(bid), j = null;
  if(bk) (bk.batches || []).forEach(function(x){ if(x.batch === batchId) j = x; });
  if(!j) return;
  state.mctx = mctxOf(bk, j);
  renderModal();
  $("modal").hidden = false;
}
function renderModal(){
  var c = state.mctx;
  if(!c) return;
  var bk = c.bk, j = c.j;
  var style = (state.mstyle === "auto") ? (c.ready ? "hero" : "score") : state.mstyle;
  var box = document.querySelector(".modalbox");
  if(box) box.className = "modalbox cmp";
  $("modal").dataset.style = style;
  var st = !c.th ? '<span class="badge dim">—</span>'
         : (!j.task ? '<span class="badge dim">待起投</span>'
         : (c.pass ? '<span class="badge ok">达标</span>'
         : (c.ready ? '<span class="badge warn">过门槛 · 未达标</span>' : '<span class="badge dim">未到门槛</span>')));
  $("mtitle").innerHTML = '<span class="mkdot" style="background:' + bk.color + '">' + bk.id + '</span>' +
    esc(bk.topic || ("桶 " + bk.id)) +
    '<span class="cmpchip">' + esc(j.label || "") + ' · ' + esc(j.start || "") + ' 起投</span>' + st +
    '<span class="cmpstyles">' + MSTYLES.map(function(m){
      return '<button data-mstyle="' + m[0] + '"' + (state.mstyle === m[0] ? ' class="on"' : '') + '>' + m[1] + '</button>';
    }).join("") + '</span>';
  $("mbody").innerHTML =
    '<div class="cmpmeta"><div class="cmpprog"><b class="num">' + fmt(c.e) + '</b><span>／ 门槛 ' +
      (c.th ? fmt(c.th) : "—") + '</span><span class="barwrap"><span class="bar" style="width:' +
      (c.th ? Math.min(100, c.e / c.th * 100).toFixed(1) : 0) + '%;background:' + bk.color +
      '"></span></span></div><div class="cmpadv">' + c.act + '</div></div>' +
    '<div class="cmprule"></div>' +
    (style === "hero" ? bodyHero(c) : bodyScore(c));
}

function ideaBtn(batch, bid){                 // 「调整思路」小图标（灯）：点了开弹窗
  return '<button class="idea" data-idea="' + esc(batch) + "|" + esc(bid) + '" title="看调整思路" ' +
         'aria-label="看调整思路"><svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">' +
         '<path d="M8 1.7a4.1 4.1 0 0 0-2.4 7.4c.4.3.6.7.6 1.2v.3h3.6v-.3c0-.5.2-.9.6-1.2A4.1 4.1 0 0 0 8 1.7Z" ' +
         'fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>' +
         '<path d="M6.6 12.6h2.8M7.2 14.2h1.6" fill="none" stroke="currentColor" ' +
         'stroke-width="1.3" stroke-linecap="round"/></svg></button>';
}
function openIdea(key){                        // 弹窗：这次为什么这么调（说明 = 复盘动作.yaml 的 note）
  var p = String(key).split("|"), batch = p[0], bid = p[1];
  var j = ((DATA.batchJudge || {})[batch] || []).filter(function(r){ return r.bucket === bid; })[0];
  if(!j || !j.action) return;
  var bl = batchById(batch);
  var box = document.querySelector(".modalbox");
  if(box) box.className = "modalbox";         // 回到窄的（待复盘/对比那两个弹窗各有自己的类）
  $("mtitle").textContent = (topicOf(j) || ("桶 " + bid)) + " · 调整思路";
  $("mbody").innerHTML =
    '<div class="mline"><span class="k">批次</span><span>' + esc(bl ? bl.label : batch) + "</span></div>" +
    '<div class="mline"><span class="k">本次调整</span><span>留 ' +
      ((j.action.keep || []).join("、") || "—") + " ｜ 下 " +
      ((j.action.drop || []).join("、") || "—") + "</span></div>" +
    '<div class="mline"><span class="k">调整思路</span><span>' + esc(j.action.note) + "</span></div>";
  $("modal").hidden = false;
}
function closeIdea(){ if($("modal")) $("modal").hidden = true; }

// ---- 待复盘（2026-09-30）：跨活动的「到门槛 · 没复盘 · 还在投」清单 ----
// 口径在服务端（`perf_payload.todo_rows()`，与 /api/perf 同一套判定），页面只负责画 + 跳转：
// 页面一次只有一个活动的数据，所以这份清单必须问服务端的 `/api/todo`。
function loadTodo(){
  if(window.__DATA__ || !AID) return;         // 单文件版没有服务；活动没定下来先不问
  fetch("api/todo", { cache:"no-store" }).then(function(r){
    if(!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(function(j){
    TODO = j || {count: 0, items: []};
    var btn = $("todobtn"), n = $("todocount");
    if(!btn) return;
    btn.hidden = !TODO.count;                 // 一条都没有 → 整个按钮不出现（不占地方）
    if(n) n.textContent = TODO.count > 99 ? "99+" : (TODO.count || "");   // 角标最多三位，别把按钮撑大
    btn.title = TODO.count ? ("待复盘 " + TODO.count + " 条（到门槛 · 还没复盘）") : "待复盘";
  }).catch(function(){});
}
function openTodo(){
  if(!TODO || !TODO.count) return;
  $("mtitle").textContent = "待复盘";
  var h = '<table class="todotb"><thead><tr><th>活动</th><th>批次</th><th>桶 / 人群</th>' +
          '<th class="c">曝光 / 门槛</th><th class="n">点击</th><th class="n">点击率</th><th>判定</th>' +
          '</tr></thead><tbody>';
  h += TODO.items.map(function(it, i){
    var p = Math.min(100, it.threshold ? it.exposure / it.threshold * 100 : 0);
    return '<tr data-goto="' + i + '" class="gorow"><td>' + esc(it.activity) + '</td>' +
      '<td>' + esc(it.batchLabel || it.batch) + '</td>' +
      '<td><b>' + esc(it.bucket) + '</b> <span class="hint">' + esc(topicOf(it)) + '</span></td>' +
      '<td class="c"><span class="barwrap" style="width:70px"><span class="bar" ' +
        'style="width:' + p.toFixed(1) + '%;background:var(--accent)"></span></span> ' +
        '<span class="num">' + fmt(it.exposure) + ' / ' + fmt(it.threshold) + '</span></td>' +
      '<td class="n num">' + fmt(it.click) + '</td>' +
      '<td class="n num">' + pct(it.click, it.exposure) + '</td>' +
      '<td>' + (it.pass ? '<span class="badge ok">达标</span>'
                        : '<span class="badge warn">过门槛 · 未达标</span>') + '</td></tr>';
  }).join("");
  $("mbody").innerHTML = h + '</tbody></table>';
  var box = document.querySelector(".modalbox");
  if(box) box.className = "modalbox wide";    // 列多，这个弹窗宽一点（调整思路那个还是窄的）
  $("modal").hidden = false;
}
function gotoItem(i){
  var it = (TODO && TODO.items || [])[i];
  if(!it) return;
  closeIdea();
  if(it.activityId && it.activityId !== AID && actsHas(it.activityId)){
    switchActivity(it.activityId);                     // 跨活动：换活动（2026-10-08 起不再"落批"）
    if(state && it.bucket) state.bs = it.bucket;
  } else if(state && it.bucket){
    state.bs = it.bucket;                              // 同活动：把「批次之间」切到这个桶
    renderAll();
  }
}
function renderAll(){ renderHead(); renderBuckets(); renderBatchStats(); }
document.addEventListener("click", function(ev){
  var t = ev.target.closest ? ev.target.closest("button,[data-cmp],[data-bs],[data-bexp],[data-goto]") : null;
  if(!t) return;
  if(t.dataset.mstyle){ state.mstyle = t.dataset.mstyle; renderModal(); }  // 弹窗里切风格
  else if(t.dataset.idea){ openIdea(t.dataset.idea); }     // 小图标：只开弹窗，不展开行（closest 先命中它）
  else if(t.dataset.goto){ gotoItem(+t.dataset.goto); }     // 待复盘清单：跳到那一批
  else if(t.dataset.mode){ state.mode = t.dataset.mode; renderBatchStats(); }
  else if(t.dataset.bs){ state.bs = t.dataset.bs; state.exp = {}; renderBatchStats(); }
  else if(t.dataset.cmp){                                   // 点桶行 / 点某批文案行 → 三条对比大弹窗
    var cp = t.dataset.cmp.split("|");
    openCompare(cp[0], cp[1]);
  }
  else if(t.dataset.bexp){                       // 批次之间：点一行展开这一批的三条文案（可多开）
    state.exp[t.dataset.bexp] = !state.exp[t.dataset.bexp];
    renderBatchStats();
  }
});
// ---- 多活动（2026-09-28）：下拉切换器；每个活动的取数状态、流水、配额各一份 ----
function actQuery(extra){                      // ?activity=…（单文件版没有 AID 就返回空）
  var qs = [];
  if(AID) qs.push("activity=" + encodeURIComponent(AID));
  if(extra) qs.push(extra);
  return qs.length ? ("?" + qs.join("&")) : "";
}
function esc(s){
  return String(s).replace(/[&<>"]/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c];
  });
}
function actsHas(id){
  for(var i=0;i<ACTS.length;i++){ if(ACTS[i].id === id) return true; }
  return false;
}
function clearPanels(){                        // 切活动 / 加载失败：先把上一个活动的数字清掉
  ["buckets","ctlmode","ctlbs","batchstats"].forEach(function(k){
    var el = $(k); if(el) el.innerHTML = "";
  });
}
function bootActivities(res){
  ACTS = (res && res.activities) || [];
  var saved = null;
  try { saved = localStorage.getItem(LS_KEY); } catch(e){}
  AID = (saved && actsHas(saved)) ? saved : ((res && res.default) || (ACTS.length ? ACTS[0].id : null));
  var sel = $("actsel");
  if(sel){
    sel.innerHTML = ACTS.map(function(a){
      return '<option value="'+esc(a.id)+'">'+esc(a.label)+
             ((a.db && a.db.days) ? "" : "（库里还没有数据）")+'</option>';
    }).join("");
    sel.value = AID || "";
    sel.hidden = !ACTS.length;
    sel.onchange = function(){ switchActivity(this.value); };
  }
  if($("ttl")) $("ttl").hidden = !!ACTS.length;   // 有下拉时下拉就是标题，同一个名字不写两遍
}
function loadActivities(){
  fetch("api/activities", { cache:"no-store" }).then(function(r){
    if(!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(function(res){
    bootActivities(res);
    loadFromServer();
    loadFetchState();
    loadTodo();                     // 待复盘角标：跨所有活动，得等 AID 定下来才问
  }).catch(function(e){
    $("subline").textContent = "拿不到活动清单（" + e.message +
      "）：确认本地服务在跑——web/app.py 或双击 web/start.bat。";
  });
}
function switchActivity(id, keep){             // keep：切过去之后落到哪一批（待复盘清单点行用）
  if(!id || id === AID) return;
  AID = id;
  try { localStorage.setItem(LS_KEY, id); } catch(e){}
  if($("actsel")) $("actsel").value = id;      // 待复盘点行是程序化切活动：下拉得跟着走
  state = null;                                // 切活动不保界面状态：两个活动的桶和日期区间都不一样
  clearPanels();
  loadFromServer(keep);
  loadFetchState();
  loadTodo();
}
function loadFromServer(keep){
  if(window.__DATA__){ boot(window.__DATA__, keep); return; }   // 单文件版：数据就在文件里
  fetch("api/perf" + actQuery(), { cache:"no-store" }).then(function(r){
    if(!r.ok){
      return r.json().catch(function(){ return {}; }).then(function(j){
        throw new Error(j.error || ("HTTP " + r.status));
      });
    }
    return r.json();
  }).then(function(d){ boot(d, keep); }).catch(function(e){
    clearPanels();
    if($("ttl")) $("ttl").textContent = "数据加载失败";
    $("subline").textContent = e.message +
      (/^HTTP /.test(e.message) ? "——确认本地服务在跑（web/app.py，或双击 web/start.bat）" : "");
  });
}
function currentView(){                        // 刷新前后要保住的界面状态
  return { mode: state.mode, bs: state.bs };
}
function loadFetchState(){
  if(window.__DATA__){                       // 单文件版没有服务：取数 / 刷新 / 切换器都藏起来
    if($("fetchbtn")) $("fetchbtn").hidden = true;
    if($("fetchstate")) $("fetchstate").hidden = true;
    if($("actsel")) $("actsel").hidden = true;
    if($("todobtn")) $("todobtn").hidden = true;
    if($("refresh")) $("refresh").style.marginLeft = "auto";
    return;
  }
  if(!AID) return;                           // 活动清单还没到手，等它来了再问
  fetch("api/fetch/status" + actQuery(), { cache:"no-store" }).then(function(r){ return r.json(); }).then(function(st){
    var btn = $("fetchbtn");
    FRESH = {lastFetchTime: st.lastFetchTime || "", auto: st.auto || null};
    if(DATA) renderHead();
    if(!btn) return;
    // 一天只取一次（昨天是终值）；别的活动在取数时也点不了——浏览器只有一只，取数是串行的。
    // 2026-10-09 起取数是**一次刷全部活动**，所以禁用看 todayDoneAll（所有活动都取过才算今天取过）
    btn.disabled = !!st.running || !!st.busy || !!st.todayDoneAll;
    // 按钮只剩图标（2026-09-28 用户定：基本永远"今天已取"，文字占地方）——状态全放悬浮提示
    var recent = st.lastFetchTime ? (" · 最近取数 " + st.lastFetchTime) : "";
    btn.title = st.busy ? ("另一个活动正在取数（" + st.busyWith + "），等这一批跑完再点")
              : (st.running ? "取数中…"
              : (st.todayDoneAll ? ("今天所有活动都已取数" + (st.lastFetchTime ? "（" + st.lastFetchTime + "）" : ""))
              : ((st.todayDone ? "取数（本活动今天已取，会把还没取的活动补上）"
                               : "取数（把昨天的数固定下来）") + recent)));
  }).catch(function(){});
}
function statemsg(text, cls){                  // 页头那行只用来报"正在进行 / 完毕"
  var el = $("fetchstate");
  el.className = "hint" + (cls ? " " + cls : "");
  el.textContent = text || "";
}
function clearStatemsgLater(ms){
  setTimeout(function(){ statemsg(""); }, ms || 4000);
}
function pollFetch(keep){
  // 2026-10-09：一次刷**全部活动**（服务端按 `?all=1` 给这一批的进度），所以轮询的是批次，
  // 不是"当前活动"——页头那行显示"正在刷新 2/3：火山…"，跑完一次性换表 + 刷角标。
  fetch("api/fetch/status" + actQuery("all=1"), { cache:"no-store" }).then(function(r){ return r.json(); }).then(function(st){
    // 服务端还是旧版（页面是静态文件、立刻生效；app.py 改了要重启服务）→ 退回"只看当前活动"的老轮询，
    // 否则这里会把"没有 batch 字段"当成"已跑完"，刷新看起来秒完成、表格其实没换。
    if(!st.batch){
      var w0 = (st.mode === "today") ? "刷新" : "取数";
      if(st.running || st.busy){
        statemsg(st.running ? ("正在" + w0 + "…") : ("正在取数（" + st.busyWith + "）…"));
        setTimeout(function(){ pollFetch(keep); }, 400);
        return;
      }
      if($("refresh")) $("refresh").classList.remove("spin");
      if($("fetchbtn")) $("fetchbtn").classList.remove("spin");
      if(st.ok){
        loadFromServer(keep);
        loadTodo();
        statemsg(w0 + "完毕！", "ok");
        clearStatemsgLater();
      } else if(st.error){
        statemsg(st.error, "warn");
      }
      setTimeout(loadFetchState, 2000);
      return;
    }
    var b = st.batch || {}, items = b.items || [], word = (b.mode === "today") ? "刷新" : "取数";
    if(b.running){
      var cur = items.filter(function(i){ return i.state === "running"; })[0] ||
                items.filter(function(i){ return i.state === "pending"; })[0];
      statemsg("正在" + word + "（" + Math.min(items.length, (b.done || 0) + 1) + "/" + items.length +
               (cur ? "：" + cur.label : "") + "）…");
      setTimeout(function(){ pollFetch(keep); }, 400);   // 2026-09-24：1.2s → 0.4s，刷新完感知上少等最多 0.8s
      return;
    }
    if($("refresh")) $("refresh").classList.remove("spin");
    if($("fetchbtn")) $("fetchbtn").classList.remove("spin");
    var bad = items.filter(function(i){ return i.state === "error"; });
    var okN = items.filter(function(i){ return i.state === "ok"; }).length;
    var skipN = items.filter(function(i){ return i.state === "skipped"; }).length;
    loadFromServer(keep);                      // 刷新时保住当前选中的时间段/口径
    loadTodo();                                // 新数进来 → 待复盘角标跟着更新（服务端已作废那份缓存）
    if(bad.length){
      statemsg(word + "完毕：" + okN + " 个成功、" + bad.length + " 个失败（" +
               bad.map(function(i){ return i.label; }).join("、") + "）：" +
               (bad[0].error || ""), "warn");
    } else {
      statemsg(word + "完毕！" + (items.length > 1 ? ("（" + okN + " 个活动" +
               (skipN ? "，" + skipN + " 个今天已取过" : "") + "）") : ""), "ok");
      clearStatemsgLater();
    }
    setTimeout(loadFetchState, 2000);
  }).catch(function(){ setTimeout(function(){ pollFetch(keep); }, 1500); });
}
function startFetch(todayOnly){
  var btn = todayOnly ? $("refresh") : $("fetchbtn"), keep = state ? currentView() : null;
  if(todayOnly){
    btn.classList.remove("spin");
    void btn.offsetWidth;                     // 重启动画：箭头一直转，直到跑完
    btn.classList.add("spin");
    statemsg("正在刷新…");
  } else {
    btn.disabled = true;
    btn.classList.add("spin");                 // 图标按钮：转起来就行，不写文字（写文字会把图标顶掉）
    statemsg("正在取数…");
  }
  // 一次刷全部活动（2026-10-09 用户定）：`all=1` + 当前活动（服务端让它排头，先跑）
  fetch("api/fetch" + actQuery("all=1" + (todayOnly ? "&today=1" : "")), { method:"POST" }).then(function(r){
    return r.json().then(function(j){ return { ok:r.ok, j:j }; });
  }).then(function(res){
    if(!res.ok){
      btn.classList.remove("spin");
      statemsg((res.j.error || "取数没起来") + "（登录态过期就跑 wait_login.py）", "warn");
      setTimeout(loadFetchState, 1500);
      return;
    }
    pollFetch(keep);          // 服务端是"起个后台任务就返回"，所以箭头由 pollFetch 在跑完后停
  }).catch(function(e){
    btn.classList.remove("spin");
    statemsg("请求失败：" + e.message, "warn");
    setTimeout(loadFetchState, 1500);
  });
}
if(window.__DATA__){ boot(window.__DATA__); } else { loadActivities(); }
if($("refresh")) $("refresh").onclick = function(){
  if(window.__DATA__){                       // 单文件版没有服务：只能重读文件里那份数据
    statemsg("刷新完毕！", "ok");
    clearStatemsgLater();
    loadFromServer(currentView());
    return;
  }
  startFetch(true);                          // 刷新 = 拉今天的实时数（随时可点）
};
if($("fetchbtn")) $("fetchbtn").onclick = function(){ startFetch(false); };
if($("todobtn")) $("todobtn").onclick = openTodo;
if($("modalx")) $("modalx").onclick = closeIdea;
if($("modal")) $("modal").onclick = function(ev){ if(ev.target === this) closeIdea(); };   // 点遮罩关掉
document.addEventListener("keydown", function(ev){ if(ev.key === "Escape") closeIdea(); });
loadFetchState();
if(!window.__DATA__) setInterval(freshTick, 60000);   // 服务版：每 60 秒看看自动刷新有没有更新数据
