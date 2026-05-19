import socket

UDP_IP = "0.0.0.0"      # 监听所有接口
UDP_PORT = 9988

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

print(f"🚀 正在监听 UDP 端口 {UDP_PORT}...")

while True:
    data, addr = sock.recvfrom(65535)  # 最大缓冲区
    print(f"📬 收到 {len(data)} 字节来自 {addr}")
    try:
        print("内容:", data.decode('utf-8')[:100])  # 显示前100字符
    except:
        print("非文本数据，跳过打印")