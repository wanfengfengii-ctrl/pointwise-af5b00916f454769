# 双记录器联检

白班用已冻结的测点组向两台独立记录器发起一张联检单。设备仍可接入新读，值班员仍可办单仪取读。样例固定 X 属 A、Y 属 B，初始为 X 第 1 代 7 count、Y 第 1 代 11 count。联检仍用冻结组的次序和换算规则，样例得 14、22 μm/s，阈值为 14，只有 Y 超限。

## 站端办理

新增 `capture.intake.take_joint(station, ports, shift_id, capture_id, group_id, generations, *, before_publish_commit=None)`。`generations` 是与冻结组完全对应、可任意排列的具名代次对。`ports` 是由站点固定配置创建的两个具名端口组成的字典，端口的 `channels` 是其固定负责的通道元组，每个测点只属一个端口，联检组选中两个端口的通道。记录器各用独立库，站端仅经端口联系设备。首次登记固定班次、组号、代次及测点对应的端口名。重传同参可续办，异参或与普通单互用单号抛 `RequestConflict`。同站一张联检单尚未签发或撤销结清时，另一号返回待查，之后可重新办理。

用现有 `CaptureStatus(capture_id, 'pending')` 表示未查实或撤销尚未结清，用 `CaptureStatus(capture_id, 'invalid')` 表示撤销结清。没有新的交流中断且所需证据均可取得时，调用应办至终局。明确不可暂扣时整单撤销。两台均确认暂扣后才可决定实取，决定须能在重开后沿原号续办，失答不可改变裁决。只认可与所绑端口及原单、本地具名代次相符的设备结果。两台各自实取的终局均查实后，才可返回按冻结规则签成的原有 `SignedCapture`。

签发钩子沿用 README.md 中普通发布的提交边界与异常语义。签存失败不留下新成果、首执或班账增量，两份已查实的原据仍可用 `ports=None` 续签。已结案的原单也可传 `None` 重领原结果。现场离线后，`receive` 和 `shift` 仍能核对按原组序存档的原值、代次、事件号、出处及首执，联检只进班账一次。

## 记录器端口

`port.call(operation, binding)` 转发一次操作，回到站端时本地操作已结束。`binding` 沿用 `TakeBinding`，单号和规程版本与原单相同，代次向量只含本端口负责的原组成员并保留相对次序。提供 `device.joint_take` 的 `prepare`、`commit`、`abort`、`status`，每项接收 `(device_path, binding)`，夹具以对应的同名操作转发。结果具有 `binding`、`state`、`group` 三个属性，状态分别可能为未登记 `pending`、不可暂扣 `invalid`、已暂扣 `prepared`、已实取 `taken`、已撤销 `aborted`。只有实取结果附 `TakenGroup`，内容须是本端实际取走的原据。允许查询及同参重投，同号异参拒绝，操作重投不得第二次改变资格或实取，已有终局不能改判。`status` 只查询。端口可能在调用前中断，也可能在设备本地提交后丢失应答，两者都以 `DeviceExchangeInterrupted` 表示。每台设备的原号状态须在关库重开后仍可查询。

暂扣整份本地成员，同时保全其中的指定代次，任一成员已经不可用时不得留下部分暂扣。暂扣只限制普通取读消费该代次。如果一个普通单的原组仅因暂扣而不能取，返回待查，同一普通单可以续办。新代可照常到站并被普通单取走。已暂扣原代次即使后来换代也可由本联检实取，且不能清掉新代。撤销后，未出现新代的原读恢复普通资格。出现过新代的旧读不得恢复，同值新代已经被取走时也一样。保留未经联检的单仪工作流、旧成果和全部原回归。

## 联调

`joint_fixture.py` 用 `examples/day.json` 安装样例站库及各自只收所属测点的记录器库。`Lab.ports` 转发传入的设备方法，`before(name, operation, binding)` 可在转发前中断，`after(name, operation, binding, outcome)` 可在本地提交后丢响应，也可在两次调用之间安排一次锁存或普通取读。`python3 -B joint_fixture.py` 可先检查夹具与原设备接口。

`python3 -B joint_fixture.py verify` 先跑原回归，再检查两个撤销轨迹和实取失答后的续签。两条撤销轨迹都在一侧已暂扣时让另一侧换代，其中一条在暂扣侧另有同值新代并已实取。前者恢复未换代原读，后者不得恢复被替代的旧读。失答轨迹查实双份原据后注入签存失败，移开两个设备库后应仍可签成 7、11 的原组并复领同一首执。`python3 -B joint_fixture.py demo` 展示停源领出的原组和班账。完成后用现有 `.pointwise-runtime.json` 的 verify 和 demo 接通这些核验与演示。
