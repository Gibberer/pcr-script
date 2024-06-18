## 露娜塔爬塔任务
该任务采用拉取视频攻略解析阵容的方式，需要提供一些额外资源才能使用：
* 安装额外依赖，例如pyav等
* 在相应目录下放置全角色图标

从视频解析阵容目前有两种方式：
1. 使用OpenCV，较慢需要分钟级别耗时
2. 使用Yolo，需要自行训练<br/>
   可以考虑基于1.的数据进行训练,效果如下：
   ![example](https://github.com/Gibberer/pcr-script/assets/30779939/d80a493a-91eb-4f8d-9d23-3609a4e5725b)

角色图片资源和Yolo的参数文件可以在[Release](https://github.com/Gibberer/pcr-script/releases/resources)里获取，解压到cache目录后可使用。

### 可能遇到的问题

#### RuntimeError: generic_type: type "_CudaDeviceProperties" is already registered!

如果使用Yolo方式，存在和PaddleOcr冲突的问题（该任务需要依赖Ocr），简单的解决方案是使用cpu版本的PaddlePaddle，这样就不会有冲突问题了。
其他方式可以参考对应Issue：PaddlePaddle/PaddleOCR#10265 再考虑适合的解决策略。

#### 拉取Bilibili视频信息时报错

相关接口可能存在风控，可以考虑通过浏览器获取Cookie，将获取的Cookie放到工程目录cache文件夹下，文件名称设置为cookie，之后发送请求就会使用该Cookie。

## 设备支持情况

脚本定义数据基于960x540分辨率的雷电模拟器，如果不是相同情况则可能有无法运行的问题，具体参考如下：

**分辨率**

|分辨率|支持情况|补充说明|
|:----|:-----:|:---|
|960x540|${\color{green}\small \texttt{支持}}$|经测试|
|1920x1080|${\color{green}\small \texttt{支持}}$|经测试|
|小于960x540|${\color{green}\small \texttt{支持}}$|经测试|
|大于960x540|${\color{green}\small \texttt{支持}}$|经测试|
|比例不为16:9|${\color{green}\small \texttt{概率支持}}$|推测，仅全面屏手机这种程度的比例变化支持的可能性很高|
---
**模拟器/设备**
|模拟器/设备|支持情况|驱动类型|补充说明|
|:----|:-----:|:---|:-----|
|雷电模拟器|${\color{green}\small \texttt{支持}}$|模拟器API|经测试|
|MUMU12|${\color{green}\small \texttt{支持}}$|模拟器API|经测试|
|其他模拟器|${\color{green}\small \texttt{支持}}$|ADB|推测，如果模拟器ADB不是默认端口的话需要手动Connect|
|真机|${\color{green}\small \texttt{支持}}$|ADB|推测|
---
**其他**
|问题描述|支持情况|补充说明|
|:----|:----:|:------|
|Windows多屏幕|${\color{green}\small \texttt{支持}}$|经测试，运行过程中调整模拟器所在屏幕无影响|
|模拟器窗口调节|${\color{red}\small \texttt{不支持}}$|雷电模拟器测试，修改窗口大小会影响获取的截图大小，不计划适配|
