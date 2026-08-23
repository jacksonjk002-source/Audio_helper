import './App.css'

const EXAMPLE_RESULT = `识别文字：
我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。

推荐碰面地点（Top 3）：
1. 星巴克（凤起路店）— 距中点约 320 米
   地址：杭州市下城区凤起路 567 号
   在高德地图中打开 ›

2. % Arabica（西湖店）— 距中点约 480 米
   地址：杭州市西湖区北山街 38 号
   在高德地图中打开 ›

3. Manner Coffee（龙翔桥店）— 距中点约 510 米
   地址：杭州市上城区平海路 58 号
   在高德地图中打开 ›

系统回复：
你们可以选下面三家咖啡店碰面：第一家星巴克离中点最近；第二家 Arabica 靠近西湖边；第三家 Manner 在龙翔桥地铁站附近，交通方便。`

function App() {
  const handleRecord = () => {
    window.alert('录音功能下一步实现')
  }

  const handlePlay = () => {
    window.alert('语音播放功能下一步实现')
  }

  return (
    <div className="app">
      <header className="header">
        <h1 className="title">语音约碰面</h1>
        <p className="subtitle">说出两人位置和想做什么，帮你找中间的碰面地点</p>
      </header>

      <main className="main">
        <button
          type="button"
          className="record-btn"
          onClick={handleRecord}
          aria-label="开始录音"
        >
          <span className="record-btn__icon" aria-hidden="true" />
          <span className="record-btn__label">按住说话</span>
        </button>

        <section className="result-panel" aria-label="识别与推荐结果">
          <h2 className="result-panel__heading">识别结果</h2>
          <pre className="result-panel__content">{EXAMPLE_RESULT}</pre>
        </section>

        <button
          type="button"
          className="play-btn"
          onClick={handlePlay}
          aria-label="播放语音回复"
        >
          <span className="play-btn__icon" aria-hidden="true" />
          播放回复
        </button>
      </main>
    </div>
  )
}

export default App
