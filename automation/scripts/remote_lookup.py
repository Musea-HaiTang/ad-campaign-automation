# -*- coding: utf-8 -*-
"""列表页按完整名称做三态查询的统一适配器。

管什么：打开一个列表、按精确名称筛选、把结果转成 FOUND / ABSENT / UNKNOWN。
不管什么：菜单、页签、筛选框怎么找（`list_page`）；远端对象怎么创建。
谁什么时候读：提交后的精确回读，以及上次中断项的定点对账。
"""
import execution_state as es
import list_page
import csdn_ui as ui
import time


def open(page, url, *, menu=None, tab=None, filter_placeholder):
    ui.goto(page, url)
    return list_page.open_list(
        page, menu=menu, tab=tab, wait_input=filter_placeholder)


def _next_page_enabled(page):
    pager = page.locator(".el-pagination:visible").last
    if not pager.count():
        return False
    nxt = pager.locator("button.btn-next").first
    return bool(
        nxt.count() and nxt.is_visible()
        and not nxt.is_disabled()
        and "is-disabled" not in (nxt.get_attribute("class") or "")
    )


def exact(lp, name, filter_placeholder, timeout=4):
    """在已打开的列表里按完整名称查询一次。"""
    before = lp.table_text()
    missing = lp.filter({filter_placeholder: name})
    if missing:
        return es.unknown("筛选框没填上：%s" % "、".join(missing))
    landed = lp.query(wait_ms=0, wait_rows=False)
    deadline = time.time() + timeout
    changed = False
    while True:
        row = lp.row_by_name(name, timeout=0)
        if row is not None:
            return es.found(
                row.id,
                reason="精确名称命中",
                row_text=row.text(),
                cells=list(row.cells),
            )
        changed = changed or lp.table_text() != before
        if time.time() >= deadline:
            break
        lp.page.wait_for_timeout(150)
    if changed or landed:
        return es.absent("查询结果已刷新，无精确名称")
    return es.unknown("点查询后表格未刷新，不能判断是否不存在")


def exact_many(lp, names_by_key, filter_placeholder, filter_value, timeout=4):
    """按共同前缀只查一次，再在本地按完整单元格名称匹配多个对象。"""
    before = lp.table_text()
    missing = lp.filter({filter_placeholder: filter_value})
    if missing:
        reason = "筛选框没填上：%s" % "、".join(missing)
        return {key: es.unknown(reason) for key in names_by_key}
    landed = lp.query(wait_ms=0, wait_rows=False)
    ready = ui.wait_for(
        lp.page, lambda: lp.table_text() != before,
        timeout=timeout, what="列表批量筛选结果刷新")
    rows = lp.rows()
    by_name = {}
    for row in rows:
        for cell in row.cells:
            text = (cell or "").strip()
            if text:
                by_name.setdefault(text, row)
    has_next = _next_page_enabled(lp.page)
    result = {}
    for key, name in names_by_key.items():
        row = by_name.get(name)
        if row is not None:
            result[key] = es.found(
                row.id, reason="批量精确名称命中",
                row_text=row.text(), cells=list(row.cells))
        elif rows or landed:
            # 查询后列表已有数据；后台在“筛选结果本来相同”时表格文字不会变化，
            # 不能因此把已返回的完整当前页当成旧数据。
            result[key] = es.absent("批量筛选当前页无精确名称")
        elif not ready:
            result[key] = es.unknown("批量筛选后表格未刷新")
        elif has_next:
            result[key] = es.unknown("共同前缀结果还有下一页，当前页未确认该名称")
        else:
            result[key] = es.absent("当前完整结果中无精确名称")
    return result
