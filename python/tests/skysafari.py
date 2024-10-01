import socket
import time
import random
import logging
import select


# This is a stress test client for the LX200 server.
# It sends random commands to the server and randomly
# disconnects to test the server's robustness.

# Set up logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Server details
SERVER_HOST = 'localhost'  # Change this if the server is on a different machine
SERVER_PORT = 4030

# List of valid LX200 commands (add more as needed)
VALID_COMMANDS = [
    ':GR#',  # Get RA
    ':GD#',  # Get DEC
    ':Q#',   # Stop all motion
    ':MS#',  # Slew to target
    ':CM#',  # Sync to target
]

# List of invalid commands
INVALID_COMMANDS = [
    ':XX#',
    ':YY#',
    ':ZZ#',
    'INVALID',
    'RANDOM',
]

# Command response timeout (in seconds)
RESPONSE_TIMEOUT = 0.5


def send_command(sock, command):
    try:
        logger.info(f"Sending command: {command}")
        sock.sendall(command.encode())

        # Wait for the response with a timeout
        ready = select.select([sock], [], [], RESPONSE_TIMEOUT)
        if ready[0]:
            response = sock.recv(1024).decode().strip()
            logger.info(f"Received response: {response}")
        else:
            logger.warning(f"No response received within {RESPONSE_TIMEOUT} seconds")
    except Exception as e:
        logger.error(f"Error sending command: {e}")


def random_disconnect(sock):
    if random.random() < 0.2:  # 20% chance to disconnect
        logger.info("Randomly disconnecting...")
        sock.close()
        return True
    return False


def test_server():
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect((SERVER_HOST, SERVER_PORT))
                logger.info("Connected to server")

                # Send 5 to 15 commands before potential disconnect
                for _ in range(random.randint(5, 15)):
                    if random.random() < 0.8:  # 80% chance of valid command
                        command = random.choice(VALID_COMMANDS)
                    else:
                        command = random.choice(INVALID_COMMANDS)

                    send_command(sock, command)

                    if random_disconnect(sock):
                        break

                    time.sleep(random.uniform(0.1, 1))  # Wait between commands

                if not sock._closed:
                    logger.info("Closing connection normally")
                    sock.close()

        except ConnectionRefusedError:
            logger.error("Connection refused. Is the server running?")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")

        time.sleep(random.uniform(1, 5))  # Wait before attempting to reconnect


if __name__ == "__main__":
    test_server()
