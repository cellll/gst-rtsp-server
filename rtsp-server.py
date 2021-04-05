# apt install -y gir1.2-gst-rtsp-server-1.0=1.14.5-0ubuntu1~18.04.1

from multiprocessing import Process, Value, Array, Manager
import time
import cv2
import gi 

gi.require_version('Gst', '1.0')
gi.require_version('GstRtspServer', '1.0') 
from gi.repository import Gst, GstRtspServer, GObject

import base64
import numpy as np
import time
import socket
import cv2
import os
import sys



# multiprocessing Shared variable 

manager = Manager()
shared_rtsp_init = Value('i', False)
shared_rtsp_req_time = Value('d', time.time())
shared_result_img_list = manager.list([])


# rtsp server
class SensorFactory(GstRtspServer.RTSPMediaFactory):
    def __init__(self, **properties): 
        super(SensorFactory, self).__init__(**properties) 
                
        self.width = 1280
        self.height = 720
        self.number_frames = 0 
        self.fps = 30
        self.duration = 1 / self.fps * Gst.SECOND  # duration of a frame in nanoseconds 
        self.launch_string = 'appsrc name=source is-live=true block=true format=GST_FORMAT_TIME ' \
                             'caps=video/x-raw,format=BGR,width={},height={},framerate={}/1 ' \
                             '! videoconvert ! video/x-raw,format=I420 ' \
                             '! x264enc speed-preset=ultrafast tune=zerolatency ' \
                             '! rtph264pay config-interval=1 name=pay0 pt=96'.format(self.width, self.height, self.fps)
        
        self.empty_frame = np.zeros(shape=(self.height, self.width, 3), dtype=np.uint8)
        self.empty_frame.fill(255)

        
    # 실제 프레임 전송 부분 
    def on_need_data(self, src, lenght):

        # inference된 결과 리스트에 있는 프레임 읽어와서 

        if len(shared_result_img_list) == 0:
            frame = self.empty_frame
        else:
            frame = shared_result_img_list.pop(0)
            
        frame = cv2.resize(frame, (self.width, self.height))

        data = frame.tostring() 
        buf = Gst.Buffer.new_allocate(None, len(data), None)
        buf.fill(0, data)
        buf.duration = self.duration
        timestamp = self.number_frames * self.duration
        buf.pts = buf.dts = int(timestamp)
        buf.offset = timestamp
        self.number_frames += 1
        retval = src.emit('push-buffer', buf) 

        #print('pushed buffer, frame {}, duration {} ns, durations {} s'.format(self.number_frames, self.duration, self.duration / Gst.SECOND)) 
        shared_rtsp_req_time.value = time.time()
        self.empty_frame = frame
        
        # 오류 시 다시 초기화하기 위한 init 변수 업데이트 
        if retval != Gst.FlowReturn.OK: 
            shared_rtsp_init.value = False
            print(retval) 

            
    def do_create_element(self, url): 
        return Gst.parse_launch(self.launch_string) 

    # config
    def do_configure(self, rtsp_media): 
        self.number_frames = 0 
        appsrc = rtsp_media.get_element().get_child_by_name('source') 
        appsrc.connect('need-data', self.on_need_data) 
        shared_rtsp_init.value = True

# rtsp gstserver
class GstServer(GstRtspServer.RTSPServer): 
    def __init__(self, **properties): 
        super(GstServer, self).__init__(**properties) 
        self.factory = SensorFactory() 
        self.factory.set_shared(True) 
        self.get_mount_points().add_factory("/test", self.factory) 
        self.attach(None) 
 

def rtsp_start():
    loop = GObject.MainLoop() 
    GObject.threads_init() 
    Gst.init(None) 
    server = GstServer() 
    print ("GstServer initialized")

    loop.run()
    
# rtsp client의 요청이 2초 이상 끊기면 저장해두었던 프레임 삭제 (list 비움)
def reset_rtsp_req_time():
    while True:
        req_time = shared_rtsp_req_time.value
        if time.time()-req_time > 2 and shared_rtsp_init.value == True:
            shared_rtsp_init.value = False
            while len(shared_result_img_list) > 0:
                shared_result_img_list.pop()
            print ('RTSP reset')
        time.sleep(1)

# main 
def inference():
    
    cap = cv2.VideoCapture('/root/xaiva/video/street01.mp4')
    count = 0
    
    width, height = 1280, 720

    # 프레임 읽어서 inference 
    while True:
       
        if cap.get(cv2.CAP_PROP_POS_FRAMES) >=  cap.get(cv2.CAP_PROP_FRAME_COUNT):
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0.0)
        
        ret, frame = cap.read()
        frame = cv2.resize(frame, (width, height))
#         frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        count += 1

        if shared_rtsp_init.value == True:
            shared_result_img_list.append(frame)

        count = 0
    

# multiprocess 지정 
Process(target=rtsp_start, args=()).start()
Process(target=reset_rtsp_req_time, args=()).start()


#run main
inference()

# rtsp://localhost:8554/test
# cap = cv2.VideoCapture('rtsp://localhost:8554/test')