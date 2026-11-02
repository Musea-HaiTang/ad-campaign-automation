(function () {
  "use strict";

  var DATA = null;
  var DAYS = [];
  var BUCKETS = [];
  var BATCHES = [];
  var FIRST = "";
  var LAST = "";
  var ACTIVE_ACTIVITY = null;
  var state = null;
  var ACTIVITIES = [];
  var AID = null;
  var FRESH_KEY = "";
  var LS_KEY = "ad_dashboard_activity";
  var DATE_PICKER = null;
  var MODAL_TIMER = null;

  var DATE_CHARTS = [
    ["trend", "趋势"],
    ["composition", "点击构成"],
    ["heatmap", "异常热力"],
    ["small", "分桶小倍图"]
  ];
  var BATCH_CHARTS = [
    ["trend", "批次趋势"],
    ["bars", "批次对比"],
    ["bullet", "门槛完成度"]
  ];
  var OTHER = { id: "other", name: "其他桶", color: "#94A3B8" };

  function $(id) { return document.getElementById(id); }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"]/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[char];
    });
  }

  function fmt(value) {
    return Number(value || 0).toLocaleString("zh-CN");
  }

  function pct(value) {
    return (Number(value || 0) * 100).toFixed(2) + "%";
  }

  function pp(value) {
    return (value >= 0 ? "+" : "") + (Number(value || 0) * 100).toFixed(2) + "pp";
  }

  function short(date) {
    return date ? date.slice(5).replace("-", "/") : "—";
  }

  function full(date) {
    return date ? date.replaceAll("-", ".") : "—";
  }

  function weekday(dateText) {
    return "日一二三四五六"[new Date(dateText + "T00:00:00").getDay()];
  }

  function dateKey(date) {
    var year = date.getFullYear();
    var month = String(date.getMonth() + 1).padStart(2, "0");
    var day = String(date.getDate()).padStart(2, "0");
    return year + "-" + month + "-" + day;
  }

  function dateText(value) {
    return value ? value.replaceAll("-", "/") : "—";
  }

  function monthKey(value) {
    return value ? value.slice(0, 7) : "";
  }

  function shiftMonth(value, delta) {
    var parts = value.split("-");
    var date = new Date(Number(parts[0]), Number(parts[1]) - 1 + delta, 1);
    return dateKey(date).slice(0, 7);
  }

  function monthText(value) {
    var parts = value.split("-");
    return Number(parts[0]) + " 年 " + Number(parts[1]) + " 月";
  }

  function adaptPayload(payload) {
    var days = payload.days || [];
    var partialDays = new Set(payload.partialDays || []);
    var buckets = payload.buckets || [];
    var bucketCells = payload.bucketCells || {};
    var daily = days.map(function (dateText) {
      var cells = buckets.map(function (bucket) {
        var values = (((bucketCells[bucket.id] || {}).all || {})[dateText]) || [0, 0, 0, 0];
        var exposure = Number(values[0] || 0);
        var clicks = Number(values[1] || 0);
        return {
          id: bucket.id,
          exposure: exposure,
          clicks: clicks,
          ctr: exposure ? clicks / exposure : 0
        };
      });
      var exposure = cells.reduce(function (sum, cell) { return sum + cell.exposure; }, 0);
      var clicks = cells.reduce(function (sum, cell) { return sum + cell.clicks; }, 0);
      return {
        date: dateText,
        weekday: weekday(dateText),
        exposure: exposure,
        clicks: clicks,
        ctr: exposure ? clicks / exposure : 0,
        partial: partialDays.has(dateText),
        buckets: cells
      };
    });

    var statsByBatch = {};
    (payload.batchStats || []).forEach(function (row) {
      if (!statsByBatch[row.batch]) statsByBatch[row.batch] = [];
      statsByBatch[row.batch].push(row);
    });
    var judgeByBatch = {};
    Object.keys(payload.batchJudge || {}).forEach(function (batchId) {
      judgeByBatch[batchId] = {};
      (payload.batchJudge[batchId] || []).forEach(function (row) {
        judgeByBatch[batchId][row.bucket] = row;
      });
    });

    var batches = (payload.batches || []).map(function (batch) {
      var stats = statsByBatch[batch.id] || [];
      if (!stats.length) return null;
      var exposure = stats.reduce(function (sum, row) { return sum + Number(row.e || 0); }, 0);
      var clicks = stats.reduce(function (sum, row) { return sum + Number(row.c || 0); }, 0);
      var activeDays = Math.max.apply(null, stats.map(function (row) {
        return Number(row.activeDays != null ? row.activeDays : (row.days || 0));
      }));
      var runDays = Math.max.apply(null, stats.map(function (row) {
        return Number(row.runDays != null ? row.runDays : (row.days || 0));
      }));
      var lasts = stats.map(function (row) { return row.runLast || row.last; }).filter(Boolean);
      var last = lasts.length ? lasts.sort().slice(-1)[0] : null;
      return {
        id: batch.id,
        label: batch.label || batch.id,
        start: batch.start || (stats[0] && stats[0].start) || "",
        end: last,
        days: runDays,
        activeDays: activeDays,
        exposure: exposure,
        clicks: clicks,
        ctr: exposure ? clicks / exposure : 0,
        partial: !!(days.length && last === days[days.length - 1]),
        buckets: stats.map(function (row) {
          var rowExposure = Number(row.e || 0);
          var rowClicks = Number(row.c || 0);
          var judged = (judgeByBatch[batch.id] || {})[row.bucket] || null;
          return {
            id: row.bucket,
            exposure: rowExposure,
            clicks: rowClicks,
            ctr: rowExposure ? rowClicks / rowExposure : 0,
            judgeExposure: judged ? Number(judged.exposure || 0) : null,
            judgeClicks: judged ? Number(judged.click || 0) : null,
            days: Number(row.runDays != null ? row.runDays : (row.days || 0)),
            activeDays: Number(row.activeDays != null ? row.activeDays : (row.days || 0)),
            first: row.runFirst || row.first,
            last: row.runLast || row.last
          };
        })
      };
    }).filter(Boolean);

    return {
      id: payload.activityId || AID || "",
      label: payload.label || "投放看板",
      first: days[0] || "",
      last: days.length ? days[days.length - 1] : "",
      days: daily,
      buckets: buckets.map(function (bucket) {
        return {
          id: bucket.id,
          name: bucket.name,
          color: bucket.color,
          topic: bucket.topic || "",
          threshold: Number(bucket.threshold || 1),
          currentBatch: bucket.currentBatch || null,
          refBatch: bucket.refBatch || null,
          thresholdReading: bucket.thresholdReading || null
        };
      }),
      batches: batches
    };
  }

  function validDate(value, fallback) {
    return value && value >= FIRST && value <= LAST ? value : fallback;
  }

  function initialState(keep) {
    var sevenStart = DAYS[Math.max(0, DAYS.length - 7)];
    var defaultStart = sevenStart ? sevenStart.date : FIRST;
    var saved = keep || {};
    var view = saved.view === "batch" ? "batch" : "date";
    var bucket = saved.bucket;
    if (bucket !== "all" && !BUCKETS.some(function (item) { return item.id === bucket; })) bucket = null;
    if (!bucket) bucket = view === "batch" && BUCKETS.length ? BUCKETS[0].id : "all";
    if (view === "batch" && bucket === "all" && BUCKETS.length) bucket = BUCKETS[0].id;
    return {
      view: view,
      size: saved.size === 0 || saved.size === 1 || saved.size === 7 ? saved.size : 7,
      start: validDate(saved.start, defaultStart),
      end: validDate(saved.end, LAST),
      bucket: bucket,
      metric: ["exposure", "clicks", "ctr"].indexOf(saved.metric) >= 0 ? saved.metric : "clicks",
      analysisMode: saved.analysisMode === "chart" ? "chart" : "detail",
      dateChart: DATE_CHARTS.some(function (item) { return item[0] === saved.dateChart; })
        ? saved.dateChart : "trend",
      batchChart: BATCH_CHARTS.some(function (item) { return item[0] === saved.batchChart; })
        ? saved.batchChart : "trend",
      expandedDates: Array.isArray(saved.expandedDates)
        ? saved.expandedDates.filter(function (date) {
          return DAYS.some(function (day) { return day.date === date; });
        })
        : []
    };
  }

  function boot(payload, keep) {
    DATA = adaptPayload(payload);
    DAYS = DATA.days || [];
    BUCKETS = DATA.buckets || [];
    BATCHES = DATA.batches || [];
    FIRST = DATA.first || "";
    LAST = DATA.last || "";
    if (!ACTIVITIES.length) ACTIVITIES = [{ id: DATA.id, label: DATA.label }];
    ACTIVE_ACTIVITY = ACTIVITIES.find(function (item) { return item.id === DATA.id; }) ||
      { id: DATA.id, label: DATA.label };
    AID = DATA.id || AID;
    state = initialState(keep);
    state.activity = AID;
    renderAll(false);
  }

  function filteredDays() {
    return DAYS.filter(function (day) {
      return day.date >= state.start && day.date <= state.end;
    });
  }

  function bucketDef(id) {
    return BUCKETS.find(function (bucket) { return bucket.id === id; }) || null;
  }

  function selectedBucket() {
    return state.bucket === "all" ? null : bucketDef(state.bucket);
  }

  function bucketShortName(bucket) {
    var name = (bucket && bucket.name) || "—";
    var prefix = ((ACTIVE_ACTIVITY && ACTIVE_ACTIVITY.id) || "") + "-";
    return prefix && name.indexOf(prefix) === 0 ? name.slice(prefix.length) : name;
  }

  function batchLabel(batch) {
    return batch.label === "首批" ? "初始批" : batch.label;
  }

  function batchMetrics(batch) {
    var bucket = selectedBucket();
    if (!bucket) return batch;
    var cell = batch.buckets.find(function (item) { return item.id === bucket.id; }) ||
      { exposure: 0, clicks: 0, ctr: 0, days: 0 };
    var days = Number(cell.days || batch.days || 0);
    return {
      exposure: Number(cell.exposure || 0),
      clicks: Number(cell.clicks || 0),
      ctr: Number(cell.ctr || 0),
      days: days,
      first: cell.first || batch.start,
      last: cell.last || batch.end,
      avgExposure: Number(cell.exposure || 0) / Math.max(days, 1),
      avgClicks: Number(cell.clicks || 0) / Math.max(days, 1)
    };
  }

  function selectedBatches() {
    var bucket = selectedBucket();
    if (!bucket) return [];
    return BATCHES.filter(function (batch) {
      var cell = batch.buckets.find(function (item) { return item.id === bucket.id; });
      return cell && (cell.exposure > 0 || cell.clicks > 0);
    }).sort(function (a, b) {
      return (batchMetrics(a).first || a.start || "").localeCompare(batchMetrics(b).first || b.start || "");
    });
  }

  function bucketBatchLabel(batch) {
    var ordinal = selectedBatches().findIndex(function (item) { return item.id === batch.id; }) + 1;
    return batch.label === "首批" ? "第 " + ordinal + " 批 · 初始" : "第 " + ordinal + " 批";
  }

  function dayMetrics(day) {
    var bucket = selectedBucket();
    if (!bucket) return day;
    var cell = day.buckets.find(function (item) { return item.id === bucket.id; }) ||
      { exposure: 0, clicks: 0, ctr: 0 };
    return {
      exposure: Number(cell.exposure || 0),
      clicks: Number(cell.clicks || 0),
      ctr: Number(cell.ctr || 0)
    };
  }

  function bucketStartDate(bucketId) {
    var row = DAYS.find(function (day) {
      var cell = day.buckets.find(function (item) { return item.id === bucketId; });
      return cell && (cell.exposure > 0 || cell.clicks > 0);
    });
    return row ? row.date : null;
  }

  function isBucketStarted(day, bucketId) {
    var start = bucketStartDate(bucketId);
    return !start || day.date >= start;
  }

  function previousDateRows() {
    var rows = filteredDays();
    var start = DAYS.findIndex(function (day) { return day.date === state.start; });
    return DAYS.slice(Math.max(0, start - rows.length), start);
  }

  function rankedBuckets() {
    var rows = selectedBucket() ? [selectedBucket()] : BUCKETS;
    return rows.map(function (def) {
      var clicks = filteredDays().reduce(function (sum, day) {
        var cell = day.buckets.find(function (item) { return item.id === def.id; });
        return sum + (cell ? cell.clicks : 0);
      }, 0);
      return { def: def, clicks: clicks };
    }).sort(function (a, b) { return b.clicks - a.clicks; });
  }

  function topBucketDefs(limit) {
    return rankedBuckets().slice(0, limit || 5).map(function (item) { return item.def; });
  }

  function stackedBucketDefs() {
    if (selectedBucket()) return [selectedBucket()];
    if (BUCKETS.length <= 6) return BUCKETS.slice();
    return topBucketDefs(5).concat(OTHER);
  }

  function valueOfCell(cell, metric) {
    if (metric === "exposure") return Number(cell.exposure || 0);
    if (metric === "ctr") return Number(cell.ctr || 0) * 100;
    return Number(cell.clicks || 0);
  }

  function metricValue(metrics) {
    if (state.metric === "exposure") return Number(metrics.exposure || 0);
    if (state.metric === "ctr") return Number(metrics.ctr || 0) * 100;
    return Number(metrics.clicks || 0);
  }

  function chartDayValue(day) {
    return metricValue(dayMetrics(day));
  }

  function metricName() {
    if (state.metric === "exposure") return "曝光";
    if (state.metric === "ctr") return "点击率";
    return "点击";
  }

  function valueText(value) {
    if (state.metric === "ctr") return Number(value || 0).toFixed(2) + "%";
    if (value >= 10000) return (value / 10000).toFixed(1) + "万";
    if (value >= 1000) return (value / 1000).toFixed(1) + "k";
    return Number(value || 0).toFixed(value % 1 ? 1 : 0);
  }

  function sumRows(rows) {
    var exposure = rows.reduce(function (sum, day) { return sum + dayMetrics(day).exposure; }, 0);
    var clicks = rows.reduce(function (sum, day) { return sum + dayMetrics(day).clicks; }, 0);
    return { exposure: exposure, clicks: clicks, ctr: exposure ? clicks / exposure : 0 };
  }

  function bucketSelectMarkup(includeAll) {
    var current = state.bucket === "all" ? "全部" : bucketShortName(bucketDef(state.bucket));
    var options = (includeAll ? [{ value: "all", label: "全部" }] : []).concat(
      BUCKETS.map(function (bucket) {
        return { value: bucket.id, label: bucketShortName(bucket) };
      })
    );
    return '<label class="bucketpick">' + (includeAll ? "分桶 / 产品" : "选择分桶 / 产品") +
      '<span class="customselect"><button type="button" class="selectbtn" data-buckettoggle data-value="' +
      esc(state.bucket || "") + '" aria-haspopup="listbox" aria-expanded="false"><span>' +
      esc(current) + '</span><i class="selectarrow" aria-hidden="true"></i></button>' +
      '<span class="selectmenu" role="listbox" aria-label="选择分桶或产品" hidden>' +
      options.map(function (option) {
        return '<button type="button" class="selectoption" data-bucketvalue="' + esc(option.value) +
          '" role="option" aria-selected="' + (option.value === state.bucket ? "true" : "false") +
          '">' + esc(option.label) + '</button>';
      }).join("") + '</span></span></label>';
  }

  function dateFilterMarkup() {
    var ranges = [[1, "今天"], [7, "近 7 天"], [0, "全部"]];
    return '<div class="modebar"><div class="seg">' + ranges.map(function (range) {
      return '<button data-size="' + range[0] + '" class="' +
        (state.size === range[0] ? "on" : "") + '">' + range[1] + '</button>';
    }).join("") + '</div><div class="dates"><span>日期</span><div class="daterangepicker">' +
      '<button type="button" class="daterangetoggle" data-datetoggle aria-haspopup="dialog" ' +
      'aria-expanded="false" aria-label="选择日期范围"><span class="datevalue">' +
      dateText(state.start) + '</span><span class="datesep">至</span><span class="datevalue">' +
      dateText(state.end) + '</span><svg class="dateicon" viewBox="0 0 16 16" aria-hidden="true">' +
      '<rect x="2.2" y="3.2" width="11.6" height="10.2" rx="1.8" fill="none" stroke="currentColor" ' +
      'stroke-width="1.3"/><path d="M2.4 6.3h11.2M5.2 1.9v2.8M10.8 1.9v2.8" fill="none" ' +
      'stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg></button>' +
      '<div class="datepicker" id="datepickerpanel" role="dialog" aria-label="选择日期范围" hidden></div>' +
      '</div></div>' + bucketSelectMarkup(true) +
      '<span class="metatext">' + filteredDays().length +
      ' 天 · 最新一天为未完整日</span></div>';
  }

  function datePickerMarkup() {
    if (!DATE_PICKER) return "";
    var parts = DATE_PICKER.month.split("-");
    var year = Number(parts[0]);
    var monthIndex = Number(parts[1]) - 1;
    var first = new Date(year, monthIndex, 1);
    var gridStart = new Date(year, monthIndex, 1 - ((first.getDay() + 6) % 7));
    var today = dateKey(new Date());
    var cells = [];
    for (var index = 0; index < 42; index++) {
      var date = new Date(gridStart);
      date.setDate(gridStart.getDate() + index);
      var key = dateKey(date);
      var classes = ["calday"];
      if (key.slice(0, 7) !== DATE_PICKER.month) classes.push("outside");
      if (key === today) classes.push("today");
      if (key > DATE_PICKER.start && key < DATE_PICKER.end) classes.push("in-range");
      if (key === DATE_PICKER.start) classes.push("range-start");
      if (key === DATE_PICKER.end) classes.push("range-end");
      if (DATE_PICKER.start === DATE_PICKER.end && key === DATE_PICKER.start) {
        classes.push("range-single");
      }
      var disabled = key < FIRST || key > LAST;
      cells.push('<button type="button" class="' + classes.join(" ") + '" data-calday="' + key +
        '" aria-label="' + dateText(key) + '" aria-pressed="' +
        (key >= DATE_PICKER.start && key <= DATE_PICKER.end ? "true" : "false") + '"' +
        (disabled ? " disabled" : "") + '>' + date.getDate() + '</button>');
    }
    var firstMonth = monthKey(FIRST);
    var lastMonth = monthKey(LAST);
    var canPrev = DATE_PICKER.month > firstMonth;
    var canNext = DATE_PICKER.month < lastMonth;
    var hint = DATE_PICKER.stage === "end"
      ? "开始日 " + dateText(DATE_PICKER.start) + " · 请选择结束日"
      : "已选 " + dateText(DATE_PICKER.start) + " 至 " + dateText(DATE_PICKER.end);
    return '<div class="datepickerhead"><button type="button" class="calnav" data-calnav="-1" ' +
      'aria-label="上个月"' + (canPrev ? "" : " disabled") + '>‹</button><b>' +
      monthText(DATE_PICKER.month) + '</b><button type="button" class="calnav" data-calnav="1" ' +
      'aria-label="下个月"' + (canNext ? "" : " disabled") + '>›</button></div>' +
      '<div class="calweek"><span>一</span><span>二</span><span>三</span><span>四</span>' +
      '<span>五</span><span>六</span><span>日</span></div><div class="calgrid">' +
      cells.join("") + '</div><div class="calhint">' + hint + '</div>' +
      '<div class="datepickeractions"><button type="button" class="caltextbtn" data-calaction="cancel">取消</button>' +
      '<button type="button" class="caltextbtn" data-calaction="today">今天</button>' +
      '<button type="button" class="calapplybtn" data-calaction="apply">应用</button></div>';
  }

  function renderDatePicker() {
    var panel = $("datepickerpanel");
    if (panel && DATE_PICKER) panel.innerHTML = datePickerMarkup();
  }

  function openDatePicker() {
    DATE_PICKER = {
      start: state.start,
      end: state.end,
      month: monthKey(state.end || state.start),
      stage: null
    };
    var range = document.querySelector(".daterangepicker");
    var toggle = document.querySelector("[data-datetoggle]");
    var panel = $("datepickerpanel");
    renderDatePicker();
    if (range) range.classList.add("open");
    if (toggle) toggle.setAttribute("aria-expanded", "true");
    if (panel) panel.hidden = false;
    requestAnimationFrame(function () {
      var selected = panel && panel.querySelector(".range-end:not(:disabled)");
      if (selected) selected.focus({ preventScroll: true });
    });
  }

  function closeDatePicker(focusToggle) {
    DATE_PICKER = null;
    var range = document.querySelector(".daterangepicker");
    var toggle = document.querySelector("[data-datetoggle]");
    var panel = $("datepickerpanel");
    if (range) range.classList.remove("open");
    if (toggle) toggle.setAttribute("aria-expanded", "false");
    if (panel) {
      panel.hidden = true;
      panel.innerHTML = "";
    }
    if (focusToggle && toggle) toggle.focus({ preventScroll: true });
  }

  function batchFilterMarkup() {
    return '<div class="modebar">' + bucketSelectMarkup(false) +
      '<span class="metatext">已选 ' + esc(bucketShortName(selectedBucket())) + ' · 共 ' +
      selectedBatches().length + ' 批 · 按起投日排序</span></div>';
  }

  function summaryMarkup() {
    if (state.view === "date") {
      var rows = filteredDays();
      var total = sumRows(rows);
      return '<div class="summarygrid"><div><span>区间曝光</span><b class="num">' +
        fmt(total.exposure) + '</b></div><div><span>区间点击</span><b class="num">' +
        fmt(total.clicks) + '</b></div><div><span>区间点击率</span><b class="num">' +
        pct(total.ctr) + '</b></div><div><span>完整日</span><b class="num">' +
        rows.filter(function (day) { return !day.partial; }).length + '</b></div></div>';
    }
    var batches = selectedBatches();
    if (!batches.length) return '<div class="empty">当前分桶没有可展示的批次数据</div>';
    var exposure = batches.reduce(function (sum, batch) {
      return sum + batchMetrics(batch).exposure;
    }, 0);
    var clicks = batches.reduce(function (sum, batch) {
      return sum + batchMetrics(batch).clicks;
    }, 0);
    return '<div class="summarygrid"><div><span>批次数量</span><b class="num">' +
      batches.length + '</b></div><div><span>累计曝光</span><b class="num">' + fmt(exposure) +
      '</b></div><div><span>累计点击</span><b class="num">' + fmt(clicks) +
      '</b></div><div><span>累计点击率</span><b class="num">' +
      pct(exposure ? clicks / exposure : 0) + '</b></div></div>';
  }

  function bucketThresholdItem(def) {
    var reading = def.thresholdReading || null;
    var batch = reading && reading.batch ? {
      id: reading.batch,
      label: reading.label || reading.batch
    } : null;
    var exposure = reading ? Number(reading.exposure || 0) : 0;
    var threshold = Number(def.threshold || 0);
    var reached = threshold > 0 && exposure >= threshold;
    var progress = threshold > 0 ? Math.min(100, exposure / threshold * 100) : 0;
    return {
      def: def,
      batch: batch,
      exposure: exposure,
      threshold: threshold,
      reached: reached,
      progress: progress
    };
  }

  function thresholdRows() {
    return BUCKETS.map(bucketThresholdItem);
  }

  function updateThresholdButton() {
    var button = $("thresholdbtn");
    var count = $("thresholdbtncount");
    if (!button || !count) return;
    var rows = thresholdRows();
    var reached = rows.filter(function (row) { return row.reached; }).length;
    button.hidden = !rows.length;
    count.textContent = reached + " / " + rows.length;
    button.classList.toggle("has-reached", reached > 0);
    button.setAttribute("aria-label", "查看当前批门槛，已达 " + reached + " 个，共 " + rows.length + " 个");
    button.title = rows.length
      ? "当前批门槛：已达 " + reached + " / " + rows.length + "，点击查看"
      : "当前批门槛";
  }

  function thresholdOverviewMarkup() {
    if (!BUCKETS.length) return "";
    var rows = thresholdRows();
    var reached = rows.filter(function (row) { return row.reached; }).length;
    return '<div class="thresholdmodalbody"><div class="thresholdmodalintro">' +
      '<span class="thresholdcount">已达 ' + reached + ' / ' + rows.length + '</span>' +
      '<span class="hint">按每桶当前批累计曝光；无当前批读数时使用参考批 · 点击任一桶可筛选</span>' +
      '</div><div class="thresholdgrid">' + rows.map(function (row) {
        var name = bucketShortName(row.def);
        var state = row.reached ? "已达门槛" : (row.batch ? "未到门槛" : "尚无批次数据");
        var title = name + " · " + state + " · 曝光 " + fmt(row.exposure) +
          (row.threshold ? " / " + fmt(row.threshold) : "") +
          (row.batch ? " · " + row.batch.label : "");
        return '<button type="button" class="thresholditem ' + (row.reached ? "reached" : "unreached") +
          '" data-thresholdbucket="' + esc(row.def.id) + '" title="' + esc(title) +
          '" aria-label="' + esc(title + "，点击筛选") + '">' +
          '<span class="thresholditemhead"><span class="thresholdname"><i class="slotdot" style="background:' +
          row.def.color + '"></i>' + esc(name) + '</span><span class="thresholdstate">' + state +
          '</span></span><span class="thresholdbar"><i style="width:' + row.progress.toFixed(1) +
          '%;background:' + (row.reached ? "var(--ok)" : row.def.color) + '"></i></span>' +
          '<span class="thresholdnumbers"><span>' + fmt(row.exposure) + '</span><span>' +
          (row.threshold ? " / " + fmt(row.threshold) : " / —") + '</span></span></button>';
      }).join("") + '</div></div>';
  }

  function activeChart() {
    return state.view === "date" ? state.dateChart : state.batchChart;
  }

  function supportsMetric() {
    return ["composition", "bullet"].indexOf(activeChart()) < 0;
  }

  function chartToolbar() {
    var charts = state.view === "date" ? DATE_CHARTS : BATCH_CHARTS;
    var disabled = !supportsMetric();
    return '<div class="charttoolbar"><div class="charttypes">' + charts.map(function (chart) {
      return '<button class="fbtn ' + (activeChart() === chart[0] ? "on" : "") +
        '" data-' + state.view + 'chart="' + chart[0] + '">' + chart[1] + '</button>';
    }).join("") + '</div><div class="seg" title="' +
      (disabled ? "当前图表使用固定指标" : "切换图表指标") + '">' +
      ["exposure", "clicks", "ctr"].map(function (metric) {
        var label = { exposure: "曝光", clicks: "点击", ctr: "点击率" }[metric];
        return '<button data-metric="' + metric + '" class="' +
          (state.metric === metric ? "on" : "") + '"' + (disabled ? " disabled" : "") + '>' +
          label + '</button>';
      }).join("") + '</div><span class="meta">' + (state.view === "date"
        ? filteredDays().length + " 天 · 按日口径"
        : esc(bucketShortName(selectedBucket())) + " · " + selectedBatches().length + " 批") +
      '</span></div>';
  }

  function chartIntro() {
    var intro = {
      trend: ["双周期趋势", "原始日数据 + 7 日均线；棕色标记按起投日汇总，点击可看批次清单。"],
      composition: ["点击构成", "点击最多的前 5 个桶单独展示，其余合并为“其他桶”，避免颜色过多。"],
      heatmap: ["异常热力", "颜色表示" + metricName() + "强弱，点击单元格可定位具体日期和桶。"],
      small: ["分桶小倍图", "最多展示点击前 5 个桶；每个桶单独一张趋势，不和其他桶共用纵轴。"],
      bars: ["批次对比", "所选桶的每个批次一行，按同一指标横向比较。"],
      bullet: ["门槛完成度", "所选桶各批次的累计曝光与同一门槛对比。"]
    }[activeChart()];
    if (state.view === "batch" && activeChart() === "trend") {
      intro = ["批次趋势", bucketShortName(selectedBucket()) + "按起投时间展示全部 " +
        selectedBatches().length + " 个批次的" + metricName() + "。"];
    } else if (state.view === "batch" && activeChart() === "bars") {
      intro = ["批次对比", bucketShortName(selectedBucket()) + "的全部批次按" + metricName() + "横向排列。"];
    } else if (state.view === "batch" && activeChart() === "bullet") {
      intro = ["门槛完成度", "逐批查看" + bucketShortName(selectedBucket()) + "的累计曝光与门槛。"];
    }
    if (state.metric === "ctr" && supportsMetric()) {
      intro[1] += " 当前图按 CTR 实际范围缩放，真实的 0 值会保留。";
    }
    return '<div class="chartintro"><b>' + esc(intro[0]) + '</b><span>' + esc(intro[1]) + '</span></div>';
  }

  function chartLegend() {
    if (state.view === "date" && activeChart() === "trend") {
      return '<div class="legendrow"><span class="legendkey"><i class="legendline"></i>' +
        metricName() + '</span><span class="legendkey"><i class="legendline" ' +
        'style="background:#0F766E"></i>7 日均线</span><span class="legendkey">' +
        '<i class="legenddash"></i>前一周期</span><span class="legendkey">' +
        '<i class="legenddot" style="background:#B45309"></i>批次上线</span></div>';
    }
    if (state.view === "date" && activeChart() === "composition") {
      return '<div class="legendrow">' + stackedBucketDefs().map(function (bucket) {
        return '<span class="legendkey"><i class="legenddot" style="background:' + bucket.color +
          '"></i>' + esc(bucket.name) + '</span>';
      }).join("") + '</div>';
    }
    if (state.view === "date" && activeChart() === "heatmap") {
      return '<div class="legendrow"><span class="heatscale">低 <i class="heatgradient"></i> 高</span>' +
        '<span>颜色深浅只表示相对大小，单元格内保留数值</span></div>';
    }
    if (state.view === "batch" && activeChart() === "bullet") {
      return '<div class="legendrow"><span class="legendkey"><i class="legenddot" ' +
        'style="background:#2563EB"></i>当前曝光</span><span class="legendkey">' +
        '<i class="legenddot" style="background:#B45309"></i>门槛</span></div>';
    }
    return "";
  }

  function batchLaunchEvents(rows) {
    var bucket = selectedBucket();
    var visibleDates = new Set(rows.map(function (row) { return row.date; }));
    var byDate = {};
    BATCHES.forEach(function (batch) {
      if (!batch.start || !visibleDates.has(batch.start)) return;
      var cell = bucket ? batch.buckets.find(function (item) {
        return item.id === bucket.id;
      }) : batch.buckets[0];
      if (!cell) return;
      var def = bucket || bucketDef(cell.id);
      (byDate[batch.start] = byDate[batch.start] || []).push({
        bucket: def ? bucketShortName(def) : cell.id,
        label: batchLabel(batch)
      });
    });
    return Object.keys(byDate).sort().map(function (date) {
      var items = byDate[date].sort(function (a, b) {
        return (a.bucket + a.label).localeCompare(b.bucket + b.label);
      });
      return { date: date, items: items };
    });
  }

  function rollingAverage(day) {
    var index = DAYS.findIndex(function (item) { return item.date === day.date; });
    var values = DAYS.slice(Math.max(0, index - 6), index + 1).map(chartDayValue)
      .filter(function (value) { return value !== null; });
    return values.length ? values.reduce(function (sum, value) { return sum + value; }, 0) / values.length : null;
  }

  function lineChart() {
    var rows = filteredDays();
    var prev = previousDateRows();
    var W = 1080;
    var H = 250;
    var m = { l: 54, r: 24, t: 32, b: 36 };
    var iw = W - m.l - m.r;
    var ih = H - m.t - m.b;
    var values = rows.map(chartDayValue);
    var averages = rows.map(rollingAverage);
    var prevValues = prev.map(chartDayValue);
    var allValues = values.concat(averages, prevValues)
      .filter(function (value) { return value !== null; });
    var yMin = 0;
    var yMax = Math.max.apply(null, allValues.concat([1])) * 1.13;
    if (state.metric === "ctr") {
      var dataMin = Math.min.apply(null, allValues);
      var dataMax = Math.max.apply(null, allValues);
      var span = Math.max(dataMax - dataMin, .03);
      yMin = Math.max(0, dataMin - span * .35);
      yMax = dataMax + span * .35;
    }
    var yScale = function (value) { return (value - yMin) / Math.max(yMax - yMin, .0001); };
    var step = iw / Math.max(rows.length, 1);
    var currentPoints = rows.map(function (day, index) {
      return {
        d: day,
        v: values[index],
        x: m.l + step * index + step / 2,
        y: values[index] === null ? null : m.t + ih - yScale(values[index]) * ih
      };
    });
    var prevPoints = prev.map(function (day, index) {
      return {
        d: day,
        v: prevValues[index],
        x: m.l + step * index + step / 2,
        y: prevValues[index] === null ? null : m.t + ih - yScale(prevValues[index]) * ih
      };
    });
    var averagePoints = rows.map(function (day, index) {
      return {
        d: day,
        v: averages[index],
        x: m.l + step * index + step / 2,
        y: averages[index] === null ? null : m.t + ih - yScale(averages[index]) * ih
      };
    });
    var svg = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' +
      metricName() + '按日期趋势">';
    for (var i = 0; i <= 4; i++) {
      var y = m.t + ih * i / 4;
      svg += '<line x1="' + m.l + '" y1="' + y + '" x2="' + (W - m.r) + '" y2="' + y +
        '" stroke="#E7EDF5"/>';
      svg += '<text x="' + (m.l - 9) + '" y="' + (y + 4) +
        '" text-anchor="end" font-size="10" fill="#94A3B8">' +
        valueText(yMin + (yMax - yMin) * (1 - i / 4)) + '</text>';
    }
    batchLaunchEvents(rows).forEach(function (event) {
      var index = rows.findIndex(function (day) { return day.date === event.date; });
      if (index < 0) return;
      var x = currentPoints[index].x;
      var title = full(event.date) + " · " + event.items.length + " 个批次上线\n" +
        event.items.map(function (item) { return item.bucket + " · " + item.label; }).join("\n");
      svg += '<g class="batchmark" data-launch-date="' + event.date +
        '" tabindex="0" role="button" aria-label="' + esc(title) + '">' +
        '<title>' + esc(title) + '</title>' +
        '<rect class="batchhit" x="' + (x - 8) + '" y="' + (m.t - 20) +
        '" width="16" height="26"/>' +
        '<line class="batchstem" x1="' + x + '" y1="' + (m.t - 9) + '" x2="' + x +
        '" y2="' + (m.t + ih) + '" stroke="#B45309" stroke-width="1.2" stroke-dasharray="4 4"/>' +
        '<circle class="batchdot" cx="' + x + '" cy="' + (m.t - 9) +
        '" r="3.4" fill="#B45309" stroke="#fff" stroke-width="1.5"/></g>';
    });
    if (prevPoints.length) {
      var prevPath = "";
      var prevDrawing = false;
      prevPoints.forEach(function (point) {
        if (point.v === null || point.y === null) { prevDrawing = false; return; }
        prevPath += (prevDrawing ? "L" : "M") + point.x.toFixed(1) + "," + point.y.toFixed(1);
        prevDrawing = true;
      });
      svg += '<path d="' + prevPath + '" fill="none" stroke="#94A3B8" stroke-width="1.8" ' +
        'stroke-dasharray="6 5"/>';
      prevPoints.forEach(function (point) {
        if (point.v === null || point.y === null) return;
        svg += '<circle cx="' + point.x + '" cy="' + point.y + '" r="2.5" fill="#94A3B8"><title>' +
          full(point.d.date) + " " + metricName() + " " + valueText(point.v) + '</title></circle>';
      });
    }
    var path = "";
    var drawing = false;
    currentPoints.forEach(function (point) {
      if (point.v === null || point.y === null) { drawing = false; return; }
      path += (drawing ? "L" : "M") + point.x.toFixed(1) + "," + point.y.toFixed(1);
      drawing = true;
    });
    svg += '<path d="' + path + '" fill="none" stroke="#1D4ED8" stroke-width="2.4" ' +
      'stroke-linecap="round" stroke-linejoin="round"/>';
    var averagePath = "";
    var averageDrawing = false;
    averagePoints.forEach(function (point) {
      if (point.v === null || point.y === null) { averageDrawing = false; return; }
      averagePath += (averageDrawing ? "L" : "M") + point.x.toFixed(1) + "," + point.y.toFixed(1);
      averageDrawing = true;
    });
    svg += '<path d="' + averagePath + '" fill="none" stroke="#0F766E" stroke-width="1.8" ' +
      'stroke-linecap="round" stroke-linejoin="round"/>';
    currentPoints.forEach(function (point, index) {
      if (rows.length <= 10 || index % 2 === 0 || index === rows.length - 1) {
        svg += '<text x="' + point.x + '" y="' + (H - 11) +
          '" text-anchor="middle" font-size="10" fill="#64748B">' + short(point.d.date) + '</text>';
      }
      if (point.v === null || point.y === null) return;
      svg += '<circle cx="' + point.x + '" cy="' + point.y + '" r="' +
        (point.d.partial ? 4.3 : 3.1) + '" fill="' + (point.d.partial ? "#fff" : "#1D4ED8") +
        '" stroke="' + (point.d.partial ? "#B45309" : "#fff") +
        '" stroke-width="1.8"><title>' + full(point.d.date) + " " + metricName() + " " +
        valueText(point.v) + (point.d.partial ? "（未完整日）" : "") + '</title></circle>';
    });
    return svg + "</svg>";
  }

  function stackedChart() {
    var rows = filteredDays();
    var defs = stackedBucketDefs();
    var W = 1080;
    var H = 260;
    var m = { l: 52, r: 24, t: 22, b: 38 };
    var iw = W - m.l - m.r;
    var ih = H - m.t - m.b;
    var max = Math.max.apply(null, rows.map(function (day) { return day.clicks; }).concat([1])) * 1.13;
    var step = iw / Math.max(rows.length, 1);
    var barW = Math.max(6, Math.min(32, step * .62));
    var svg = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="每日点击按桶构成">';
    for (var i = 0; i <= 4; i++) {
      var y = m.t + ih * i / 4;
      svg += '<line x1="' + m.l + '" y1="' + y + '" x2="' + (W - m.r) + '" y2="' + y +
        '" stroke="#E7EDF5"/>';
      svg += '<text x="' + (m.l - 9) + '" y="' + (y + 4) +
        '" text-anchor="end" font-size="10" fill="#94A3B8">' +
        Math.round(max * (1 - i / 4)) + '</text>';
    }
    rows.forEach(function (day, index) {
      var x = m.l + step * index + (step - barW) / 2;
      var yBase = m.t + ih;
      defs.forEach(function (def) {
        var clicks;
        if (def.id === "other") {
          clicks = day.buckets.filter(function (cell) {
            return !topBucketDefs(5).some(function (top) { return top.id === cell.id; });
          }).reduce(function (sum, cell) { return sum + cell.clicks; }, 0);
        } else {
          var cell = day.buckets.find(function (item) { return item.id === def.id; });
          clicks = cell ? cell.clicks : 0;
        }
        var height = clicks / max * ih;
        yBase -= height;
        svg += '<rect x="' + x.toFixed(1) + '" y="' + yBase.toFixed(1) + '" width="' +
          barW.toFixed(1) + '" height="' + height.toFixed(1) + '" fill="' + def.color +
          '" opacity=".9"><title>' + full(day.date) + " " + esc(def.name) + " 点击 " +
          fmt(clicks) + '</title></rect>';
      });
      if (rows.length <= 10 || index % 2 === 0 || index === rows.length - 1) {
        svg += '<text x="' + (x + barW / 2) + '" y="' + (H - 13) +
          '" text-anchor="middle" font-size="10" fill="#64748B">' + short(day.date) + '</text>';
      }
    });
    return svg + "</svg>";
  }

  function heatmapChart() {
    var rows = selectedBucket() ? [selectedBucket()] : BUCKETS;
    var cols = filteredDays();
    var values = rows.map(function (row) {
      return cols.map(function (col) {
        var cell = col.buckets.find(function (item) { return item.id === row.id; });
        return valueOfCell(cell, state.metric);
      });
    });
    var flat = values.flat();
    var max = Math.max.apply(null, flat.concat([1]));
    var min = Math.min.apply(null, flat.concat([0]));
    return '<div class="heatgrid" style="grid-template-columns:112px repeat(' + cols.length +
      ',minmax(42px,1fr))"><span></span>' +
      cols.map(function (col) { return '<span class="heatx">' + short(col.date) + '</span>'; }).join("") +
      rows.map(function (row, rowIndex) {
        return '<span class="heatlabel"><i class="slotdot" style="background:' + row.color +
          ';margin-right:5px"></i>' + esc(row.name) + '</span>' +
          cols.map(function (col, colIndex) {
            var value = values[rowIndex][colIndex];
            var ratio = max === min ? .35 : (value - min) / (max - min);
            var background = state.metric === "ctr"
              ? "rgba(29,78,216," + (.07 + ratio * .28) + ")"
              : "rgba(29,78,216," + (.06 + ratio * .72) + ")";
            var color = ratio > .58 ? "#fff" : "#27364A";
            return '<span class="heatcell" style="background:' + background + ";color:" + color +
              '" title="' + full(col.date) + " · " + esc(row.name) + " · " + metricName() + " " +
              (state.metric === "ctr" ? value.toFixed(2) + "%" : fmt(value)) + '">' +
              (state.metric === "ctr" ? value.toFixed(2) : Math.round(value)) + '</span>';
          }).join("");
      }).join("") + '</div>';
  }

  function miniLine(values, color, labels) {
    var W = 180;
    var H = 84;
    var m = { l: 8, r: 8, t: 8, b: 16 };
    var iw = W - m.l - m.r;
    var ih = H - m.t - m.b;
    var max = Math.max.apply(null, values.concat([1])) * 1.12;
    var step = iw / Math.max(values.length - 1, 1);
    var points = values.map(function (value, index) {
      return [m.l + step * index, m.t + ih - value / max * ih];
    });
    var path = points.map(function (point, index) {
      return (index ? "L" : "M") + point[0].toFixed(1) + "," + point[1].toFixed(1);
    }).join(" ");
    var labelText = function (value) {
      return value.length === 10 ? value.slice(5).replace("-", "/") : value;
    };
    return '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="分桶趋势">' +
      points.map(function (point, index) {
        return '<circle cx="' + point[0] + '" cy="' + point[1] + '" r="2.3" fill="' + color +
          '"><title>' + esc(labels[index]) + " " + valueText(values[index]) + '</title></circle>';
      }).join("") + '<path d="' + path + '" fill="none" stroke="' + color +
      '" stroke-width="1.8"/><text x="' + m.l + '" y="' + (H - 3) +
      '" font-size="7.5" fill="#94A3B8">' + labelText(labels[0]) +
      '</text><text x="' + (W - m.r) + '" y="' + (H - 3) +
      '" text-anchor="end" font-size="7.5" fill="#94A3B8">' +
      labelText(labels[labels.length - 1]) + '</text></svg>';
  }

  function smallMultiples() {
    var cols = filteredDays();
    return '<div class="sm-grid">' + topBucketDefs(5).map(function (def) {
      var values = cols.map(function (col) {
        return valueOfCell(col.buckets.find(function (item) { return item.id === def.id; }), state.metric);
      });
      var labels = cols.map(function (col) { return full(col.date); });
      return '<div class="sm-card"><div class="sm-cardhead"><i class="legenddot" style="background:' +
        def.color + '"></i><span>' + esc(def.name) + '</span><b>' +
        valueText(values[values.length - 1]) + '</b></div>' +
        miniLine(values, def.color, labels) + '</div>';
    }).join("") + '</div>';
  }

  function batchChartValue(batch) {
    return metricValue(batchMetrics(batch));
  }

  function batchTrendChart() {
    var rows = selectedBatches();
    if (!rows.length) return '<div class="empty">当前分桶没有批次数据</div>';
    var values = rows.map(batchChartValue);
    var W = 1080;
    var H = 250;
    var m = { l: 54, r: 24, t: 30, b: 40 };
    var iw = W - m.l - m.r;
    var ih = H - m.t - m.b;
    var yMin = 0;
    var yMax = Math.max.apply(null, values.concat([1])) * 1.13;
    if (state.metric === "ctr") {
      var dataMin = Math.min.apply(null, values);
      var dataMax = Math.max.apply(null, values);
      var span = Math.max(dataMax - dataMin, .03);
      yMin = Math.max(0, dataMin - span * .35);
      yMax = dataMax + span * .35;
    }
    var yScale = function (value) { return (value - yMin) / Math.max(yMax - yMin, .0001); };
    var step = iw / Math.max(rows.length, 1);
    var points = rows.map(function (batch, index) {
      return {
        batch: batch,
        value: values[index],
        x: m.l + step * index + step / 2,
        y: m.t + ih - yScale(values[index]) * ih
      };
    });
    var svg = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="所选分桶批次趋势">';
    for (var i = 0; i <= 4; i++) {
      var y = m.t + ih * i / 4;
      svg += '<line x1="' + m.l + '" y1="' + y + '" x2="' + (W - m.r) + '" y2="' + y +
        '" stroke="#E7EDF5"/>';
      svg += '<text x="' + (m.l - 9) + '" y="' + (y + 4) +
        '" text-anchor="end" font-size="10" fill="#94A3B8">' +
        valueText(yMin + (yMax - yMin) * (1 - i / 4)) + '</text>';
    }
    var path = points.map(function (point, index) {
      return (index ? "L" : "M") + point.x.toFixed(1) + "," + point.y.toFixed(1);
    }).join(" ");
    svg += '<path d="' + path + '" fill="none" stroke="#1D4ED8" stroke-width="2.3" ' +
      'stroke-linecap="round" stroke-linejoin="round"/>';
    points.forEach(function (point, index) {
      if (rows.length <= 10 || index % 2 === 0 || index === rows.length - 1) {
        svg += '<text x="' + point.x + '" y="' + (H - 12) +
          '" text-anchor="middle" font-size="9" fill="#64748B">' +
          bucketBatchLabel(point.batch).replace(" · 初始", "") + '</text>';
      }
      svg += '<circle cx="' + point.x + '" cy="' + point.y + '" r="3.2" fill="#1D4ED8" ' +
        'stroke="#fff" stroke-width="1.5"><title>' + bucketBatchLabel(point.batch) + " · " +
        esc(batchLabel(point.batch)) + " · " + metricName() + " " + valueText(point.value) +
        '</title></circle>';
    });
    return svg + "</svg>";
  }

  function batchBarsChart() {
    var rows = selectedBatches().slice().reverse();
    if (!rows.length) return '<div class="empty">当前分桶没有批次数据</div>';
    var values = rows.map(batchChartValue);
    var max = Math.max.apply(null, values.concat([1]));
    return '<div class="batchbars">' + rows.map(function (batch, index) {
      return '<div class="batchbarrow"><div class="batchbarname" title="' +
        esc(batchLabel(batch)) + '">' + bucketBatchLabel(batch) + '</div>' +
        '<div class="batchbarline"><i style="width:' +
        Math.max(2, values[index] / max * 100) + '%"></i></div>' +
        '<div class="batchbarvalue">' + valueText(values[index]) + '</div></div>';
    }).join("") + '</div>';
  }

  function bulletChart() {
    var def = selectedBucket();
    var rows = selectedBatches().slice().reverse();
    if (!def || !rows.length) return '<div class="empty">当前分桶没有批次数据</div>';
    return '<div class="bulletwrap">' + rows.map(function (batch) {
      var cell = batch.buckets.find(function (item) { return item.id === def.id; });
      var exposure = Number(cell.judgeExposure != null ? cell.judgeExposure : cell.exposure);
      var ratio = Math.min(100, exposure / def.threshold * 100);
      return '<div class="bulletrow"><div class="bulletname" title="' + esc(batchLabel(batch)) +
        '">' + bucketBatchLabel(batch) + '</div><div style="position:relative;height:20px">' +
        '<div style="position:absolute;left:0;right:0;top:6px;height:8px;background:#E9EFF6;' +
        'border-radius:4px"></div><div style="position:absolute;left:0;width:' + ratio +
        '%;top:6px;height:8px;background:#2563EB;border-radius:4px"></div>' +
        '<i title="门槛 ' + fmt(def.threshold) + '" style="position:absolute;left:100%;top:2px;' +
        'height:16px;border-left:2px solid #B45309"></i></div><div class="bulletvalue">' +
        fmt(exposure) + " / " + fmt(def.threshold) + " · " + ratio.toFixed(0) +
        '%</div></div>';
    }).join("") + '</div>';
  }

  function chartMarkup() {
    if (state.view === "date" && state.dateChart === "trend") return lineChart();
    if (state.view === "date" && state.dateChart === "composition") return stackedChart();
    if (state.view === "date" && state.dateChart === "heatmap") return heatmapChart();
    if (state.view === "date" && state.dateChart === "small") return smallMultiples();
    if (state.view === "batch" && state.batchChart === "trend") return batchTrendChart();
    if (state.view === "batch" && state.batchChart === "bars") return batchBarsChart();
    return bulletChart();
  }

  function chartArea() {
    return '<div class="chartarea">' + chartToolbar() + chartIntro() +
      '<div class="chartbox">' + chartMarkup() + '</div><div id="chartlegend">' +
      chartLegend() + '</div></div>';
  }

  function exposureChangeMarkup(now, before, suppress) {
    if (suppress || before === null || before === undefined) return '<span class="dim">—</span>';
    var diff = now - before;
    if (diff === 0) return '<span class="dim">0 / 0.0%</span>';
    var rate = before ? diff / before * 100 : null;
    return '<span class="' + (diff > 0 ? "up" : "down") + '">' +
      (diff > 0 ? "+" : "") + fmt(diff) + " / " +
      (rate === null ? "—" : (rate >= 0 ? "+" : "") + rate.toFixed(1) + "%") + '</span>';
  }

  function ctrChangeMarkup(now, before, suppress) {
    if (suppress || before === null || before === undefined) return '<span class="dim">—</span>';
    var diff = (now - before) * 100;
    if (Math.abs(diff) < .005) return '<span class="dim">0.00pp</span>';
    return '<span class="' + (diff > 0 ? "up" : "down") + '">' + pp(diff / 100) + '</span>';
  }

  function inlineDateDetail(day) {
    var index = DAYS.findIndex(function (item) { return item.date === day.date; });
    var prev = index > 0 ? DAYS[index - 1] : null;
    var bucket = selectedBucket();
    var cells = bucket ? day.buckets.filter(function (cell) { return cell.id === bucket.id; }) : day.buckets;
    return cells.map(function (cell) {
      var def = bucketDef(cell.id);
      var prevCell = prev ? prev.buckets.find(function (item) { return item.id === cell.id; }) : null;
      var started = isBucketStarted(day, cell.id);
      var prevCtr = prevCell && prevCell.exposure ? prevCell.clicks / prevCell.exposure : null;
      return '<tr class="bucket-detail-row" data-detail-date="' + day.date + '"><td>' +
        '<i class="slotdot" style="background:' + def.color + '"></i>' + esc(def.name) + '</td>' +
        '<td class="n num">' + (started ? fmt(cell.exposure) : '<span class="dim">—</span>') + '</td>' +
        '<td class="n num">' + (started ? fmt(cell.clicks) : '<span class="dim">—</span>') + '</td>' +
        '<td class="n num">' + exposureChangeMarkup(cell.exposure,
          prevCell && prevCell.exposure, !started || day.partial) + '</td>' +
        '<td class="n num">' + (started ? pct(cell.ctr) : '<span class="dim">—</span>') + '</td>' +
        '<td class="n num">' + ctrChangeMarkup(cell.ctr, prevCtr, !started || day.partial) + '</td></tr>';
    }).join("");
  }

  function openRowDetail(id) {
    var index = state.expandedDates.indexOf(id);
    if (index >= 0) state.expandedDates.splice(index, 1);
    else state.expandedDates.push(id);
    renderTableAnchored(id);
  }

  function closeRowDetail() {
    state.expandedDates = [];
    renderTableAnchored(null);
  }

  function renderTableAnchored(id) {
    var selector = id ? '[data-date="' + id + '"]' : null;
    var oldRow = selector ? document.querySelector(selector) : null;
    var anchorTop = oldRow ? oldRow.getBoundingClientRect().top : null;
    var host = $("tablearea");
    host.innerHTML = state.view === "date" ? dateTable() : batchTable();
    requestAnimationFrame(function () {
      var row = selector ? document.querySelector(selector) : null;
      if (!row) return;
      if (anchorTop !== null) window.scrollBy(0, row.getBoundingClientRect().top - anchorTop);
      row.focus({ preventScroll: true });
    });
  }

  function dateTable() {
    var rows = filteredDays().slice().reverse();
    var maxClicks = Math.max.apply(null, rows.map(function (day) {
      return dayMetrics(day).clicks;
    }).concat([1]));
    return '<table class="dailyview"><colgroup><col style="width:24%"><col style="width:14%">' +
      '<col style="width:14%"><col style="width:18%"><col style="width:14%"><col style="width:16%">' +
      '</colgroup><thead><tr><th>日期</th><th class="n">曝光</th><th class="n">点击</th>' +
      '<th class="n">曝光日变化</th><th class="n">点击率</th><th class="n">CTR 日变化</th>' +
      '</tr></thead><tbody>' + rows.map(function (day) {
        var index = DAYS.findIndex(function (item) { return item.date === day.date; });
        var prev = index > 0 ? DAYS[index - 1] : null;
        var metrics = dayMetrics(day);
        var prevMetrics = prev ? dayMetrics(prev) : null;
        var selected = state.expandedDates.indexOf(day.date) >= 0;
        var started = !selectedBucket() || isBucketStarted(day, selectedBucket().id);
        return '<tr class="dayrow ' + (selected ? "picked" : "") + '" data-date="' + day.date +
          '" tabindex="0" aria-expanded="' + selected + '"><td><span class="datelabel"><span>' +
          short(day.date) + " 周" + day.weekday + '</span>' +
          (day.partial ? '<span class="badge partial">未完整</span>' : "") + '</span></td>' +
          '<td class="n num">' + (started ? fmt(metrics.exposure) : '<span class="dim">—</span>') + '</td>' +
          '<td class="n num">' + (started ? fmt(metrics.clicks) +
            '<span class="clickbarwrap"><span class="clickbar" style="width:' +
            Math.max(4, metrics.clicks / maxClicks * 100) + '%"></span></span>' :
            '<span class="dim">—</span>') + '</td><td class="n num">' +
          exposureChangeMarkup(metrics.exposure, prevMetrics && prevMetrics.exposure,
            !started || day.partial) + '</td><td class="n num">' +
          (started ? pct(metrics.ctr) : '<span class="dim">—</span>') + '</td>' +
          '<td class="n num">' + ctrChangeMarkup(metrics.ctr,
            prevMetrics && prevMetrics.ctr, !started || day.partial) + '</td></tr>' +
          (selected ? inlineDateDetail(day) : "");
      }).join("") + '</tbody></table>';
  }

  function batchTable() {
    var chronological = selectedBatches();
    var rows = chronological.slice().reverse();
    if (!rows.length) return '<div class="empty">当前分桶没有可展示的批次数据</div>';
    return '<table class="batchtable"><colgroup><col style="width:22%"><col style="width:15%">' +
      '<col style="width:9%"><col style="width:14%"><col style="width:14%"><col style="width:12%">' +
      '<col style="width:14%"></colgroup><thead><tr><th>批次</th><th>起投日</th>' +
      '<th class="n" title="任务状态为进行中时算到今天；下线后冻结在最后一个有数据日">进行天数</th>' +
      '<th class="n">总曝光</th><th class="n">总点击</th>' +
      '<th class="n">总点击率</th><th class="n">曝光变化</th></tr></thead><tbody>' +
      rows.map(function (batch) {
        var index = chronological.indexOf(batch);
        var prev = index > 0 ? chronological[index - 1] : null;
        var metrics = batchMetrics(batch);
        var prevMetrics = prev ? batchMetrics(prev) : null;
        return '<tr><td><b title="' +
          esc(batch.label === "首批" ? "活动初始配置生成的批次" : batch.label) + '">' +
          bucketBatchLabel(batch) + '</b></td><td>' + short(metrics.first || batch.start) +
          '</td><td class="n num">' + metrics.days + '</td><td class="n num">' +
          fmt(metrics.exposure) + '</td><td class="n num">' + fmt(metrics.clicks) +
          '</td><td class="n num">' + pct(metrics.ctr) + '</td><td class="n num">' +
          exposureChangeMarkup(metrics.exposure, prevMetrics && prevMetrics.exposure, false) +
          '</td></tr>';
      }).join("") + '</tbody></table>';
  }

  function syncViewControls() {
    document.querySelectorAll("[data-view]").forEach(function (button) {
      button.classList.toggle("on", button.dataset.view === state.view);
    });
    document.querySelectorAll("[data-analysismode]").forEach(function (button) {
      button.classList.toggle("on", button.dataset.analysismode === state.analysisMode);
    });
  }

  function syncChartControls() {
    document.querySelectorAll("[data-datechart]").forEach(function (button) {
      button.classList.toggle("on", button.dataset.datechart === state.dateChart);
    });
    document.querySelectorAll("[data-batchchart]").forEach(function (button) {
      button.classList.toggle("on", button.dataset.batchchart === state.batchChart);
    });
    var disabled = !supportsMetric();
    document.querySelectorAll("[data-metric]").forEach(function (button) {
      button.disabled = disabled;
      button.classList.toggle("on", !disabled && state.metric === button.dataset.metric);
    });
  }

  function updateChartContent() {
    var area = document.querySelector("#chartarea .chartarea");
    if (!area) return;
    syncChartControls();
    var intro = area.querySelector(".chartintro");
    if (intro) intro.outerHTML = chartIntro();
    var box = area.querySelector(".chartbox");
    if (box) box.innerHTML = chartMarkup();
    var legend = area.querySelector("#chartlegend");
    if (legend) legend.innerHTML = chartLegend();
  }

  function renderChartArea(force) {
    var host = $("chartarea");
    if (state.analysisMode !== "chart") {
      host.innerHTML = "";
      return;
    }
    if (force || !host.querySelector(".chartarea")) host.innerHTML = chartArea();
    else updateChartContent();
  }

  function renderHead() {
    var title = (ACTIVE_ACTIVITY && ACTIVE_ACTIVITY.label) || (DATA && DATA.label) || "投放看板";
    document.title = "投放看板 · " + title;
    $("ttl").textContent = title;
    $("coverage").textContent = "起投 " + FIRST + " · 数据至 " + LAST;
  }

  function renderAll(preserveScroll) {
    var y = window.scrollY;
    syncViewControls();
    var select = $("actsel");
    if (select) {
      select.innerHTML = ACTIVITIES.map(function (activity) {
        return '<option value="' + esc(activity.id) + '"' +
          (activity.id === AID ? " selected" : "") + ">" + esc(activity.label) + '</option>';
      }).join("");
      select.value = AID || "";
      select.hidden = true;
    }
    renderActivityPicker();
    $("ttl").hidden = !!ACTIVITIES.length;
    renderHead();
    $("filterbar").innerHTML = state.view === "date" ? dateFilterMarkup() : batchFilterMarkup();
    $("summary").innerHTML = summaryMarkup();
    updateThresholdButton();
    renderChartArea(true);
    $("tablearea").innerHTML = state.analysisMode === "detail"
      ? (state.view === "date" ? dateTable() : batchTable()) : "";
    if (preserveScroll) {
      requestAnimationFrame(function () {
        window.scrollTo(0, Math.min(y,
          Math.max(0, document.documentElement.scrollHeight - innerHeight)));
      });
    }
  }

  function setDateRange(start, end) {
    if (!start || !end) return;
    if (start > end) {
      var swap = start;
      start = end;
      end = swap;
    }
    state.start = start < FIRST ? FIRST : start;
    state.end = end > LAST ? LAST : end;
    state.size = null;
    state.expandedDates = [];
    renderAll(true);
  }

  function currentView() {
    if (!state) return null;
    return {
      view: state.view,
      size: state.size,
      start: state.start,
      end: state.end,
      bucket: state.bucket,
      metric: state.metric,
      analysisMode: state.analysisMode,
      dateChart: state.dateChart,
      batchChart: state.batchChart,
      expandedDates: state.expandedDates.slice()
    };
  }

  function statemsg(text, cls) {
    var element = $("fetchstate");
    element.className = "hint" + (cls ? " " + cls : "");
    element.textContent = text || "";
  }

  function clearStatemsgLater(delay) {
    setTimeout(function () { statemsg(""); }, delay || 4000);
  }

  function actQuery(extra) {
    var parts = [];
    if (AID) parts.push("activity=" + encodeURIComponent(AID));
    if (extra) parts.push(extra);
    return parts.length ? "?" + parts.join("&") : "";
  }

  function actsHas(id) {
    return ACTIVITIES.some(function (activity) { return activity.id === id; });
  }

  function clearPanels() {
    ["filterbar", "summary", "chartarea", "tablearea"].forEach(function (id) {
      var element = $(id);
      if (element) element.innerHTML = "";
    });
    $("coverage").textContent = "";
  }

  function activityOptionLabel(activity) {
    return activity.label +
      (activity.ended ? "（已收尾）" : ((activity.db && activity.db.days) ? "" : "（库里还没有数据）"));
  }

  function renderActivityPicker() {
    var picker = $("activitypicker");
    var current = $("activitycurrent");
    var menu = $("activitymenu");
    if (!picker || !current || !menu) return;
    picker.hidden = !ACTIVITIES.length;
    if (!ACTIVITIES.length) return;
    var active = ACTIVITIES.find(function (activity) { return activity.id === AID; }) || ACTIVITIES[0];
    current.textContent = activityOptionLabel(active);
    menu.innerHTML = ACTIVITIES.map(function (activity) {
      return '<button type="button" class="activityoption" role="option" data-activityvalue="' +
        esc(activity.id) + '" aria-selected="' + (activity.id === AID ? "true" : "false") + '">' +
        esc(activityOptionLabel(activity)) + '</button>';
    }).join("");
  }

  function closeActivityPicker(focusToggle) {
    var picker = $("activitypicker");
    var menu = $("activitymenu");
    var toggle = document.querySelector("[data-activitytoggle]");
    if (picker) picker.classList.remove("open");
    if (toggle) toggle.setAttribute("aria-expanded", "false");
    if (menu) menu.hidden = true;
    if (focusToggle && toggle) toggle.focus({ preventScroll: true });
  }

  function bootActivities(response) {
    ACTIVITIES = (response && response.activities) || [];
    var saved = null;
    try { saved = localStorage.getItem(LS_KEY); } catch (error) { saved = null; }
    AID = saved && actsHas(saved) ? saved : ((response && response.default) ||
      (ACTIVITIES.length ? ACTIVITIES[0].id : null));
    var select = $("actsel");
    if (select) {
      select.innerHTML = ACTIVITIES.map(function (activity) {
        return '<option value="' + esc(activity.id) + '">' + esc(activityOptionLabel(activity)) +
          '</option>';
      }).join("");
      select.value = AID || "";
      select.hidden = true;
    }
    renderActivityPicker();
    $("ttl").hidden = !!ACTIVITIES.length;
  }

  function loadActivities() {
    fetch("api/activities", { cache: "no-store" }).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    }).then(function (response) {
      bootActivities(response);
      loadFromServer();
      loadFetchState();
    }).catch(function (error) {
      $("fetchstate").textContent = "拿不到活动清单（" + error.message +
        "）：确认本地服务在跑——web/app.py 或双击 web/start-hidden.vbs。";
    });
  }

  function switchActivity(id, keep) {
    if (!id || id === AID) return;
    AID = id;
    try { localStorage.setItem(LS_KEY, id); } catch (error) { /* ignore */ }
    if ($("actsel")) $("actsel").value = id;
    renderActivityPicker();
    closeActivityPicker(false);
    state = null;
    clearPanels();
    loadFromServer(keep || null);
    loadFetchState();
  }

  function loadFromServer(keep) {
    if (window.__DATA__) {
      boot(window.__DATA__, keep);
      return;
    }
    fetch("api/perf" + actQuery(), { cache: "no-store" }).then(function (response) {
      if (!response.ok) {
        return response.json().catch(function () { return {}; }).then(function (body) {
          throw new Error(body.error || ("HTTP " + response.status));
        });
      }
      return response.json();
    }).then(function (payload) {
      boot(payload, keep);
    }).catch(function (error) {
      clearPanels();
      $("ttl").hidden = false;
      $("ttl").textContent = "数据加载失败";
      $("coverage").textContent = "数据至 —";
      $("fetchstate").textContent = error.message +
        (/^HTTP /.test(error.message) ? "——确认本地服务在跑（web/app.py，或双击 web/start-hidden.vbs）" : "");
    });
  }

  function loadFetchState() {
    if (window.__DATA__) {
      ["fetchbtn", "fetchstate", "actsel", "activitypicker"].forEach(function (id) {
        if ($(id)) $(id).hidden = true;
      });
      if ($("refresh")) $("refresh").style.marginLeft = "auto";
      return;
    }
    if (!AID) return;
    fetch("api/fetch/status" + actQuery(), { cache: "no-store" }).then(function (response) {
      return response.json();
    }).then(function (status) {
      var button = $("fetchbtn");
      if (!button) return;
      button.disabled = !!status.running || !!status.busy || !!status.todayDoneAll;
      var recent = status.lastFetchTime ? (" · 最近取数 " + status.lastFetchTime) : "";
      button.title = status.busy
        ? ("另一个活动正在取数（" + status.busyWith + "），等这一批跑完再点")
        : (status.running ? "取数中…"
        : (status.todayDoneAll
          ? ("今天所有活动都已取数" + (status.lastFetchTime ? "（" + status.lastFetchTime + "）" : ""))
          : ((status.todayDone ? "取数（本活动今天已取，会把还没取的活动补上）"
            : "取数（把昨天的数固定下来）") + recent)));
    }).catch(function () {});
  }

  function pollFetch(keep, single) {
    fetch("api/fetch/status" + actQuery(single ? "" : "all=1"), { cache: "no-store" })
      .then(function (response) { return response.json(); })
      .then(function (status) {
        if (single || !status.batch) {
          var mode0 = status.mode === "today" ? "刷新" : "取数";
          if (status.running || status.busy) {
            statemsg(status.running ? ("正在" + mode0 + "…") :
              ("正在取数（" + status.busyWith + "）…"));
            setTimeout(function () { pollFetch(keep, single); }, 400);
            return;
          }
          $("refresh").classList.remove("spin");
          $("fetchbtn").classList.remove("spin");
          if (status.ok) {
            loadFromServer(keep);
            statemsg(mode0 + "完毕！", "ok");
            clearStatemsgLater();
          } else if (status.error) {
            statemsg(status.error, "warn");
          }
          setTimeout(loadFetchState, 2000);
          return;
        }
        var batch = status.batch || {};
        var items = batch.items || [];
        var word = batch.mode === "today" ? "刷新" : "取数";
        if (batch.running) {
          var current = items.find(function (item) { return item.state === "running"; }) ||
            items.find(function (item) { return item.state === "pending"; });
          statemsg("正在" + word + "（" + Math.min(items.length, (batch.done || 0) + 1) + "/" +
            items.length + (current ? "：" + current.label : "") + "）…");
          setTimeout(function () { pollFetch(keep, single); }, 400);
          return;
        }
        $("refresh").classList.remove("spin");
        $("fetchbtn").classList.remove("spin");
        var bad = items.filter(function (item) { return item.state === "error"; });
        var okCount = items.filter(function (item) { return item.state === "ok"; }).length;
        var skipped = items.filter(function (item) { return item.state === "skipped"; });
        loadFromServer(keep);
        if (bad.length) {
          statemsg(word + "完毕：" + okCount + " 个成功、" + bad.length + " 个失败（" +
            bad.map(function (item) { return item.label; }).join("、") + "）：" +
            (bad[0].error || ""), "warn");
        } else if (batch.mode === "today") {
          statemsg("刷新完毕！", "ok");
          clearStatemsgLater();
        } else {
          statemsg(word + "完毕！" + (items.length > 1 ? ("（" + okCount + " 个活动" +
            (skipped.length ? "，跳过：" +
              skipped.map(function (item) { return item.label; }).join("、") : "") + "）") : ""), "ok");
          clearStatemsgLater();
        }
        setTimeout(loadFetchState, 2000);
      }).catch(function () {
        setTimeout(function () { pollFetch(keep, single); }, 1500);
      });
  }

  function startFetch(todayOnly) {
    var button = todayOnly ? $("refresh") : $("fetchbtn");
    var keep = state ? currentView() : null;
    if (todayOnly) {
      button.classList.remove("spin");
      void button.offsetWidth;
      button.classList.add("spin");
      statemsg("正在刷新…");
    } else {
      button.disabled = true;
      button.classList.add("spin");
      statemsg("正在取数…");
    }
    var currentActivity = ACTIVITIES.find(function (activity) { return activity.id === AID; });
    var batched = !(currentActivity && currentActivity.ended);
    var query = [];
    if (batched) query.push("all=1");
    if (todayOnly) query.push("today=1");
    fetch("api/fetch" + actQuery(query.join("&")), { method: "POST" }).then(function (response) {
      return response.json().then(function (body) { return { ok: response.ok, body: body }; });
    }).then(function (result) {
      if (!result.ok) {
        button.classList.remove("spin");
        var message = result.body.error || "取数没起来";
        statemsg(message + (/登录|未授权|401|403/.test(message) ?
          "（登录态过期就跑 wait_login.py）" : ""), "warn");
        setTimeout(loadFetchState, 1500);
        return;
      }
      pollFetch(keep, !batched);
    }).catch(function (error) {
      button.classList.remove("spin");
      statemsg("请求失败：" + error.message, "warn");
      setTimeout(loadFetchState, 1500);
    });
  }

  function openThresholdOverview() {
    if (!BUCKETS.length) return;
    clearTimeout(MODAL_TIMER);
    $("mtitle").textContent = "当前批门槛";
    $("mbody").innerHTML = thresholdOverviewMarkup();
    document.querySelector(".modalbox").className = "modalbox thresholdmodal";
    $("modal").classList.remove("closing");
    $("modal").hidden = false;
  }

  function openBatchLaunchOverview(date) {
    var event = batchLaunchEvents(filteredDays()).find(function (item) {
      return item.date === date;
    });
    if (!event) return;
    clearTimeout(MODAL_TIMER);
    $("mtitle").textContent = full(date) + " · " + event.items.length + " 个批次上线";
    $("mbody").innerHTML = '<div class="launchlist">' + event.items.map(function (item) {
      return '<div class="launchitem"><b>' + esc(item.bucket) + '</b><span>' +
        esc(item.label) + '</span></div>';
    }).join("") + '</div>';
    document.querySelector(".modalbox").className = "modalbox launchmodal";
    $("modal").classList.remove("closing");
    $("modal").hidden = false;
  }

  function closeModal() {
    var modal = $("modal");
    if (!modal || modal.hidden) return;
    clearTimeout(MODAL_TIMER);
    modal.classList.add("closing");
    var delay = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 130;
    MODAL_TIMER = setTimeout(function () {
      modal.hidden = true;
      modal.classList.remove("closing");
    }, delay);
  }

  function freshTick() {
    if (window.__DATA__ || !AID) return;
    fetch("api/fetch/status" + actQuery(), { cache: "no-store" }).then(function (response) {
      return response.json();
    }).then(function (status) {
      var key = [(status.db || {}).last, status.lastFetchTime,
        (status.auto || {}).at, status.running].join("|");
      var changed = FRESH_KEY && key !== FRESH_KEY;
      FRESH_KEY = key;
      if (changed && !status.running) {
        loadFromServer(currentView());
      }
    }).catch(function () {});
  }

  document.addEventListener("click", function (event) {
    var launchMarker = event.target.closest("[data-launch-date]");
    if (launchMarker) {
      openBatchLaunchOverview(launchMarker.dataset.launchDate);
      return;
    }
    if (event.target.closest("#thresholdbtn")) {
      openThresholdOverview();
      return;
    }
    var activityToggle = event.target.closest("[data-activitytoggle]");
    if (activityToggle) {
      var activityMenu = $("activitymenu");
      var activityOpen = activityMenu.hidden;
      document.querySelectorAll(".selectmenu,.datepicker").forEach(function (item) {
        if (item.classList.contains("datepicker") && DATE_PICKER) closeDatePicker(false);
        else if (item.classList.contains("selectmenu")) item.hidden = true;
      });
      document.querySelectorAll("[data-buckettoggle]").forEach(function (item) {
        item.setAttribute("aria-expanded", "false");
      });
      activityMenu.hidden = !activityOpen;
      activityToggle.setAttribute("aria-expanded", activityOpen ? "true" : "false");
      $("activitypicker").classList.toggle("open", activityOpen);
      return;
    }
    var activityOption = event.target.closest("[data-activityvalue]");
    if (activityOption) {
      var nextActivity = activityOption.dataset.activityvalue;
      closeActivityPicker(false);
      switchActivity(nextActivity);
      return;
    }
    if (!event.target.closest(".activitypicker")) closeActivityPicker(false);
    var thresholdItem = event.target.closest("[data-thresholdbucket]");
    if (thresholdItem) {
      var thresholdBucket = thresholdItem.dataset.thresholdbucket;
      closeModal();
      state.bucket = thresholdBucket;
      state.expandedDates = [];
      renderAll(true);
      setTimeout(function () {
        if ($("thresholdbtn")) $("thresholdbtn").focus({ preventScroll: true });
      }, 145);
      return;
    }
    var dateToggle = event.target.closest("[data-datetoggle]");
    if (dateToggle) {
      if (DATE_PICKER) closeDatePicker(false);
      else openDatePicker();
      return;
    }
    var calendarNav = event.target.closest("[data-calnav]");
    if (calendarNav && DATE_PICKER) {
      DATE_PICKER.month = shiftMonth(DATE_PICKER.month, Number(calendarNav.dataset.calnav));
      renderDatePicker();
      return;
    }
    var calendarDay = event.target.closest("[data-calday]");
    if (calendarDay && DATE_PICKER && !calendarDay.disabled) {
      var picked = calendarDay.dataset.calday;
      if (DATE_PICKER.stage === "end") {
        DATE_PICKER.end = picked;
        if (DATE_PICKER.end < DATE_PICKER.start) {
          var swap = DATE_PICKER.start;
          DATE_PICKER.start = DATE_PICKER.end;
          DATE_PICKER.end = swap;
        }
        DATE_PICKER.stage = null;
      } else {
        DATE_PICKER.start = picked;
        DATE_PICKER.end = picked;
        DATE_PICKER.stage = "end";
      }
      renderDatePicker();
      return;
    }
    var calendarAction = event.target.closest("[data-calaction]");
    if (calendarAction && DATE_PICKER) {
      var action = calendarAction.dataset.calaction;
      if (action === "cancel") {
        closeDatePicker(true);
        return;
      }
      if (action === "today") {
        var today = dateKey(new Date());
        today = today < FIRST ? FIRST : (today > LAST ? LAST : today);
        DATE_PICKER.start = today;
        DATE_PICKER.end = today;
      }
      var range = {
        start: DATE_PICKER.start,
        end: DATE_PICKER.end
      };
      DATE_PICKER = null;
      setDateRange(range.start, range.end);
      return;
    }
    if (DATE_PICKER && !event.target.closest(".daterangepicker")) closeDatePicker(false);
    var bucketToggle = event.target.closest("[data-buckettoggle]");
    if (bucketToggle) {
      var menu = bucketToggle.parentElement.querySelector(".selectmenu");
      var open = menu.hidden;
      document.querySelectorAll(".selectmenu").forEach(function (item) { item.hidden = true; });
      menu.hidden = !open;
      bucketToggle.setAttribute("aria-expanded", open ? "true" : "false");
      return;
    }
    var bucketOption = event.target.closest("[data-bucketvalue]");
    if (bucketOption) {
      state.bucket = bucketOption.dataset.bucketvalue;
      state.expandedDates = [];
      renderAll(true);
      return;
    }
    if (!event.target.closest(".customselect")) {
      document.querySelectorAll(".selectmenu").forEach(function (item) { item.hidden = true; });
    }
    var viewButton = event.target.closest("[data-view]");
    if (viewButton) {
      state.view = viewButton.dataset.view;
      if (state.view === "batch" && state.bucket === "all" && BUCKETS.length) {
        state.bucket = BUCKETS[0].id;
      }
      state.expandedDates = [];
      renderAll(true);
      return;
    }
    var analysisButton = event.target.closest("[data-analysismode]");
    if (analysisButton) {
      state.analysisMode = analysisButton.dataset.analysismode;
      state.expandedDates = [];
      syncViewControls();
      renderChartArea(true);
      $("tablearea").innerHTML = state.analysisMode === "detail"
        ? (state.view === "date" ? dateTable() : batchTable()) : "";
      return;
    }
    var sizeButton = event.target.closest("[data-size]");
    if (sizeButton) {
      state.size = Number(sizeButton.dataset.size);
      state.end = LAST;
      state.start = state.size === 0 ? FIRST : DAYS[Math.max(0, DAYS.length - state.size)].date;
      state.expandedDates = [];
      renderAll(true);
      return;
    }
    var metricButton = event.target.closest("[data-metric]");
    if (metricButton && !metricButton.disabled) {
      state.metric = metricButton.dataset.metric;
      updateChartContent();
      return;
    }
    var dateChartButton = event.target.closest("[data-datechart]");
    if (dateChartButton) {
      state.dateChart = dateChartButton.dataset.datechart;
      updateChartContent();
      return;
    }
    var batchChartButton = event.target.closest("[data-batchchart]");
    if (batchChartButton) {
      state.batchChart = batchChartButton.dataset.batchchart;
      updateChartContent();
      return;
    }
    var dateRow = event.target.closest("[data-date]");
    if (dateRow) {
      openRowDetail(dateRow.dataset.date);
      return;
    }
  });

  document.addEventListener("change", function (event) {
    if (event.target.id === "actsel") {
      switchActivity(event.target.value);
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      if (DATE_PICKER) {
        closeDatePicker(true);
        return;
      }
      var activityMenu = $("activitymenu");
      if (activityMenu && !activityMenu.hidden) {
        closeActivityPicker(true);
        return;
      }
      var openMenu = document.querySelector(".selectmenu:not([hidden])");
      if (openMenu) {
        var toggle = openMenu.parentElement.querySelector("[data-buckettoggle]");
        openMenu.hidden = true;
        if (toggle) {
          toggle.setAttribute("aria-expanded", "false");
          toggle.focus();
        }
        return;
      }
      if (!$("modal").hidden) {
        closeModal();
        return;
      }
      if (state && state.expandedDates.length) {
        closeRowDetail();
        return;
      }
    }
    if (event.key !== "Enter" && event.key !== " ") return;
    var launchMarker = event.target.closest("[data-launch-date]");
    if (launchMarker) {
      event.preventDefault();
      openBatchLaunchOverview(launchMarker.dataset.launchDate);
      return;
    }
    var dateRow = event.target.closest("[data-date]");
    if (dateRow) {
      event.preventDefault();
      openRowDetail(dateRow.dataset.date);
    }
  });

  if ($("refresh")) $("refresh").onclick = function () {
    if (window.__DATA__) {
      statemsg("刷新完毕！", "ok");
      clearStatemsgLater();
      loadFromServer(currentView());
      return;
    }
    startFetch(true);
  };
  if ($("fetchbtn")) $("fetchbtn").onclick = function () { startFetch(false); };
  if ($("modalx")) $("modalx").onclick = closeModal;
  if ($("modal")) $("modal").onclick = function (event) {
    if (event.target === this) closeModal();
  };

  if (window.__DATA__) {
    AID = window.__DATA__.activityId || "";
    boot(window.__DATA__);
    loadFetchState();
  } else {
    loadActivities();
  }
  loadFetchState();
  if (!window.__DATA__) setInterval(freshTick, 60000);
}());
