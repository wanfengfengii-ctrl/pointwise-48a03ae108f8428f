# 带区间覆盖交班契约

滨汀观测湖 V1 已支持两字段观测行、顺序报送、待交页、首执、不可变页、固定快照、压实、现行或快照读取、原行出处和同号同参重试。本文件只公开本题新增的区间覆盖契约。已有两字段入口和全部原测试必须继续工作。

## 报送入口

继续使用 `intake.requests.submit(database, partition, submission_id, rows)` 和 `intake.publish.finish(database, submission_id, fingerprint)`。

V1 行仍是 `(category, reading)`。本题的区间行是 `(category, reading, start, end)`。同一次 `submit` 的所有行必须使用同一种长度，不能混合两字段行和四字段行。`category` 沿用 V1 的去首尾空白规则并保留大小写。`reading` 必须是整数升或 `None`。`start` 与 `end` 必须是整数，且 `start < end`。坐标只用于区间语义，不要求从零开始，也不允许使用布尔值代替整数。

四字段行表示一条同类别采样在半开区间 `[start, end)` 内的总读数。非缺测读数在该区间内按均匀速率解释，速率为 `reading / (end - start)`。同一报送的区间、类别、读数和原行顺序必须进入请求身份指纹。再次使用相同报送号时，完全相同的归一化行返回原绑定。只改变区间、类别、读数、行顺序或出处绑定都必须引发 `intake.requests.SubmissionConflict`，并且不得新增页、首执或现行成员。

提交前的非法区间、混合行长度和非法读数必须在写入前拒绝。`finish` 的首执、失败回滚、丢回包复领和关闭重开语义沿用 V1。区间证据必须在待交页中保留，或通过与稳定原行坐标绑定的独立不可变证据保留。无论采用哪种表示，`finish` 重新打开数据库后都必须能完成同一报送。

## 覆盖核账入口

新增 `audit.coverage.read_coverage(database, partition, start, end, snapshot_id=None)`。

查询坐标必须是整数并满足 `start < end`。函数使用一个 SQLite 读视图解析现行成员或指定快照的完整页集。未知分区、未知快照、必需页缺失、字典缺失或无法解码时沿用 V1 的 `LookupError` 或 `PageDataError`，不得返回部分账。

函数返回 `CoverageStatement`。公开字段如下。

```text
partition: str
snapshot_id: str | None
requested_start: int
requested_end: int
status: str                  # 'ok' 或 'rejected'
reason: str | None           # 冲突时为 'conflicting-overlap'
segments: tuple[CoverageSegment, ...]
total_litres: Fraction
missing_length: int
uncovered_length: int
conflict: CoverageConflict | None
```

每个 `CoverageSegment` 包含以下字段。

```text
category: str
start: int
end: int
state: str                   # 'value'、'missing' 或 'uncovered'
litres: Fraction | None      # value 状态始终返回 Fraction，其他状态为 None
overlap: str                # 'none'、'same-rate'、'missing-only' 或 'uncovered'
sources: tuple[SourcePosition, ...]
```

每个 `CoverageConflict` 包含以下字段。

```text
category: str
start: int
end: int
sources: tuple[SourcePosition, ...]
rates: tuple[Fraction | None, ...]
```

输出先按 `category` 升序，再按 `start`、`end` 升序。对每个类别，把查询范围和所有相交采样区间的边界切成最小半开段。没有任何采样行覆盖的段返回 `state='uncovered'`、`overlap='uncovered'`、空 `sources`，并计入 `uncovered_length`。

只有 `None` 采样覆盖的段返回 `state='missing'`、`overlap='missing-only'`、`litres=None`，并计入 `missing_length`。有效读数为零的段返回 `state='value'` 和 `litres=Fraction(0)`。缺测覆盖与有效读数在同一类别的同一最小段重叠时，整次查询返回 `status='rejected'` 和 `reason='conflicting-overlap'`。

非缺测采样在同一最小段的有效速率完全相同，重叠只计一次。该段返回一条 `state='value'`，`litres` 为该速率乘以段长，`overlap='same-rate'`，并列出全部支持该段的原行出处。不同有效速率重叠时整次查询拒绝，不能交付部分 `segments` 或部分 `total_litres`。单行覆盖的段使用 `overlap='none'`。`total_litres` 是所有类别有效段的精确 `Fraction` 总和。

## 生命周期要求

`maintenance.compact.compact` 替换源页后，现行读取必须保留区间、类别、读数和原行出处的语义。`catalog.snapshots.pin` 固定的快照必须继续读取固定时刻的同一覆盖事实。关闭并重新打开数据库后，现行账、固定账和待交报送都必须沿同一身份规则工作。压实前后的现行覆盖结果、固定快照结果、缺测长度、无覆盖长度、重叠裁决和原行出处必须一致。

查询拒绝只表示该范围没有唯一可接受的覆盖解释。数据库中的报送页、首执、现行成员和快照不得因查询拒绝发生变化。报送输入或登记事务失败时，沿用 V1 的原子回滚和原材料可重试语义。

## 样例

下列两次报送都属于类别 A。

```python
submit(db, partition, 'sample-a', [('A', 8, 0, 4)])
submit(db, partition, 'sample-b', [('A', 8, 2, 6)])
```

查询 `[1,5)` 时，A 的最小段为 `[1,2)`、`[2,4)` 和 `[4,5)`，对应精确体积 2 L、4 L 和 2 L。中间段由两条原行共同支持，但只计一次，总体积为 `Fraction(8)`。

如果第二条报送改为 `('A', 10, 2, 6)`，查询 `[1,5)` 必须返回 `status='rejected'`，原因是重叠段的有效速率分别为 `2` 和 `5/2`。

类别 C 的 `(C, 0, 0, 4)` 与类别 D 的 `(D, None, 2, 6)` 可以在同一查询中同时出现。C 的有效体积为零，D 的 `[2,6)` 覆盖为缺测，两者不能混同。

## 运行清单

母项目原回归仍使用以下入口。

```text
python3 -B check_project.py
python3 -B demo.py
```

完成本题后，使用仓库根目录的 `verify_coverage.py` 核对本文件中的同速重叠、不同速率冲突、有效零与缺测、待交重开、同号异参、压实、固定快照和关闭重开场景。
