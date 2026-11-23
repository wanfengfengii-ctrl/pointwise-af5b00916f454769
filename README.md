# 海桥纸厂振动巡检站

设备员接收卷纸机振动仪的 X、Y 原始记录。巡检员按冻结的具名组预览和取读。质检复核单位、换算和超限，夜班按采集号和班次核对结果及仪器出处。

## 运行

使用 Python 3.11 及标准库，从项目根目录执行。控制台提供 `check_project.py`。

```text
python3 -B check_project.py
python3 -B demo.py
```

演示以 `examples/day.json` 的有限仪器事件在两个临时 SQLite 文件中办理。首组原读 7、11 count，倍数为 2，换算得 14、22 μm/s。阈值为 14 μm/s，只有 Y 超限。随后的复测先取走共享的 Y，Y 的新一代 31 到站后，旧联检整组失效。演示最后移开设备库并核对固定归档。

## 业务入口

```python
from capture.intake import initialize_station, take_or_resume
from device.events import InstrumentEvent
from device.latch import latch
from device.preview import preview
from handover.lookup import receive
from handover.shift_summary import shift
from profiles.channels import ChannelDefinition, ChannelRule
from profiles.versions import configure

station, device = 'station.sqlite3', 'device.sqlite3'
initialize_station(station, device, [ChannelDefinition('X', 'count')])
profile = configure(station, '卷纸机', 'X 复测', [
    ChannelRule('X', 'count', 'μm/s', 2, 14),
])
latch(device, InstrumentEvent('X', 'event-1', 7, 'recorder/01:1'))
snapshot = preview(station, device, profile.group_id)
result = take_or_resume(station, device, '白班', 'C-01', profile.group_id,
                        snapshot.generations)
assert result == receive(station, 'C-01')
assert shift(station, '白班').group_count == 1
```

- `initialize_station(station, device, catalog)` 要求两个不同的文件。首次初始化登记非空通道目录。再次初始化使用已经登记的目录，保留规程、事件、工单及正式归档。已有设备目录与站库登记冲突时拒绝开站。
- `configure(station, name, group_name, rules)` 按提交顺序冻结规则，返回 `FrozenProfile`。同一规程与组名可以发布后续版本，每版有独立 `group_id`。未知或重复通道、空组、单位不符及非法整数参数抛出 `ValueError`。
- `latch(device, InstrumentEvent(channel, event_id, raw_value, source))` 返回含原单位及代次的 `LatchedReading`。同一路的同事件同参返回原记录，槽位保持原状。非法事件及同事件异参抛出 `ValueError`。
- `preview(station, device, group_id)` 返回 `GroupPreview` 或含缺路名单的 `PreviewPending`。完整预览给出冻结规则、读数、代次、原事件及出处。未知冻结组号抛出 `KeyError`。
- `take_or_resume(station, device, shift_id, capture_id, group_id, generations)` 接受任意次序的完整具名 `(channel, generation)` 对，或同一冻结组的 `GroupPreview`。成功返回 `SignedCapture`，待查或失效返回 `CaptureStatus`。同号合法异参抛出 `RequestConflict`。设备暂不可用时可传 `None`，此时已查实的工单仍可续签。操作各自打开并关闭数据库连接。
- `device.take_history.device_outcome(device, binding)` 接受 `TakeBinding(capture_id, version_id, generations)`，代次向量使用冻结组序。返回待查、确定失效或含实际取走原组的终局。已登记原号的绑定冲突抛出 `ValueError`。
- `receive(station, capture_id)` 返回固定成果和首执，未发布返回 `None`。`shift(station, shift_id)` 返回正式组数、逐路超限次数、各采集号的逐路出处。组按采集号排序，逐路出处按冻结组序排列，空班次返回零组和空明细。两项查询只使用站库。

## 数据与提交边界

设备接纳新合法事件时记录不可变原读，并替换该通道的活动代次。整组清除与设备终局在同一设备事务中提交。设备在同一取读事务中先查原号，再比较活动代次。失配时保持所有槽位。成功的终局引用本次实际清除的原事件，所以槽位复用后仍可回读。

站库先登记请求。收到可核对的终局后，先独立保存已查实的原组，再核定并发布。原值和阈值接受带符号整数，倍数接受正整数。布尔、浮点、字符串和空值不能充当整数。精确换算使用整数乘法，超限采用严格大于。单位或证据不一致时拒绝归档。正式成果、各路明细与首执同一事务生效。提交失败时 SQLite 异常返回调用方，原号仍可续签。设备交流中断返回待查，正常重试按原绑定重新查实。

`take_or_resume` 的可选观察边界包括 `before_take(binding)`、`after_take(outcome)` 和 `before_publish_commit(connection)`。前两项分别在首次设备命令前、设备事务提交并关闭连接后执行，交流层可抛 `DeviceExchangeInterrupted` 表示命令或回包未确认。发布钩子在正式归档写入后、事务提交前执行，调用方应让发布事务管理提交与回滚。
