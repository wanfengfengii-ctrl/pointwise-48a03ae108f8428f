# 滨汀观测湖

滨汀环境资料中心接收测站的分类整升报送。入湖班可以先接纳、下一个班次再登记。档案班固定交班账并压实分区里的散页。核账班从现行账或指定快照领取各类观测行数、缺测数、整升合计和原行出处。带区间的采样报送按半开区间 `[start, end)` 和均匀速率折算体积，核账班用 `read_coverage` 领取精确体积、覆盖状态和重叠裁决。

## 运行

使用 Python 3.11 标准库。在项目根目录运行平台提供的完整核验入口和正常演示。

```text
python3 -B check_project.py
python3 -B demo.py
python3 -B verify_coverage.py
```

演示从 `observations.json` 读取一份 A 的 5 L 和缺测报送、一份 B 的 7 L 报送。在临时 SQLite 库中完成接纳、登记、交班、压实、继续登记及回收。早班账 A 为两行、缺测一行、合计 5 L。现行账增加 B 的一行 7 L。输出包含实算分类账、逐行出处、实际清理结果和重领的首执信息。

## 日班办理

1. `catalog.storage.initialize_store(database)` 建立持久结构。`catalog.partitions.ensure_partition(database, partition, initial_categories)` 建立缺失分区并返回当前写入字典编号。重复调用保留现有数据和配置过的分区字典。已有分区可以在 `demo.initialize_example(database)` 后继续使用。
2. `intake.requests.submit(database, partition, submission_id, rows)` 接收非空有序行，每行使用 `(category, reading)`，或本题的区间行 `(category, reading, start, end)`。同一次报送不得混用两种长度。类别去首尾空白并保留大小写。读数使用 Python 整数升或 `None`，支持有效零值。区间为整数且 `start < end`，布尔值不作整数坐标。分区和报送号使用非空白文本并按原值识别。接纳返回 `SubmissionBinding`，包含供下班续办的报送号与 `fingerprint`；区间、类别、读数和原行顺序都进入该指纹。
3. `intake.publish.finish(database, submission_id, fingerprint)` 原子登记待交页、结清待交并签发 `Receipt`。同号同参接纳返回同一个绑定，同一绑定再次登记返回原首执，异参引发 `SubmissionConflict`。首执中的页和字典编号记录签发时的登记结果。提交前明确失败可用原绑定续办，提交后失答可用同一绑定复领。
4. `audit.statement.read(database, partition, snapshot_id=None)` 返回 `Statement`。账目含 `page_ids`、`totals` 和 `evidence`。每类统计全部行与缺测行，合计只累加有值行，全缺测类合计为 0 L。类别名升序排列，出处按分区、报送号、从 1 开始的原行号排序。
5. `audit.coverage.read_coverage(database, partition, start, end, snapshot_id=None)` 按半开区间 `[start, end)` 返回 `CoverageStatement`。四字段行按其类别和区间均匀速率解释，相同速率的重叠只计一次并列出全部原行出处，不同速率或缺测与有效值在同一最小段重叠时整次查询 `status='rejected'`、`reason='conflicting-overlap'` 且不交付部分账。无覆盖、缺测和有效零值分别是 `uncovered`、`missing` 和 `value`。精确体积用 `Fraction`，段先按类别再按起止排序。查询与冲突裁决不改变库内任何状态。
6. `catalog.snapshots.pin(database, partition, snapshot_id)` 保存当前页成员并返回成员编号。保留中的快照号全库唯一，重复使用引发 `ValueError`。
7. `maintenance.compact.compact(database, partition, source_page_ids)` 捕获一组当前源页。重写按当前源页顺序和页内顺序解码，按类别首次出现的顺序生成精简字典。原始类别、读数、区间和出处随重写保留。
8. 安装结果返回新 `PageEntry`。新页放在第一个被替换成员的位置，其余成员相对顺序保留。选页后新增的正式页保持可见。任一来源失去替换资格时引发 `StaleSources`，可重读现行账并重新选页。
9. `catalog.snapshots.release(database, snapshot_id)` 解除保留。未知分区、报送号或快照号通过相应入口报告 `LookupError`。读取另一分区的快照按未知号处理。
10. `maintenance.reclaim.reclaim(database, partition)` 返回退役字典的 `reclaimed`、`retained` 编号元组。现行页、保留快照和待交材料的实际引用都产生保管义务。回收事务完成正文删除才返回结果。历史页登记和首执继续保存。
11. 再次调用 `read` 或 `read_coverage` 核对清理后的现行账或固定快照。成员、正文、实际字典在同一 SQLite 读视图内读取。必需数据无法完整加载、验证或解码时，引发 `PageDataError` 并拒绝交付整份账。

SQLite 写入类错误由 `catalog.storage.StorageFailure` 报告。API 的 `database` 参数接受路径字符串及路径对象。各入口自有事务。列页和字典正文的存储、目录页登记及首执同库持久化。

```python
from audit.coverage import read_coverage
from audit.statement import read
from catalog.partitions import ensure_partition
from catalog.storage import initialize_store
from intake.publish import finish
from intake.requests import submit

path = 'observations.sqlite3'
partition = '2026-11-21/west'
initialize_store(path)
ensure_partition(path, partition, ('B', 'A'))
binding = submit(path, partition, 'station-42', [(' A ', 5), ('A', None)])
receipt = finish(path, binding.submission_id, binding.fingerprint)
statement = read(path, partition)
print(receipt, statement.totals, statement.evidence)

interval_binding = submit(path, partition, 'station-43', [('A', 8, 0, 4)])
finish(path, interval_binding.submission_id, interval_binding.fingerprint)
coverage = read_coverage(path, partition, 1, 5)
print(coverage.status, coverage.total_litres, coverage.segments)
```

## 可控操作次序

`compact` 的 `after_select(selection)` 在取页读事务关闭后、重写安装前调用，可安排另一份报送登记。`finish` 的 `before_commit()` 在新页和首执已经写入事务之后调用，抛出异常会回滚此次登记。该回调在写事务内运行。`after_commit(receipt)` 在新登记提交后调用，可模拟上游失答。复领原首执时两个回调均不触发。核验使用真实 SQLite 数据库、事务、重新打开及删除拒绝触发器。
