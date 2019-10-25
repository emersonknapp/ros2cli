# Copyright 2019 Amazon.com, Inc. or its affiliates. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

import unittest

from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch.actions import OpaqueFunction

import launch_testing
import launch_testing.asserts
import launch_testing.markers
import launch_testing.tools
import launch_testing_ros.tools


import pytest

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import DurabilityPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy

from rmw_implementation import get_available_rmw_implementations

from std_msgs.msg import String


TEST_NODE = 'cli_echo_pub_test_node'
TEST_NAMESPACE = 'cli_echo_pub'


@pytest.mark.rostest
@launch_testing.parametrize('rmw_implementation', get_available_rmw_implementations())
@launch_testing.markers.keep_alive
def generate_test_description(rmw_implementation, ready_fn):
    return LaunchDescription([
        # Always restart daemon to isolate tests.
        ExecuteProcess(
            cmd=['ros2', 'daemon', 'stop'],
            name='daemon-stop',
            on_exit=[
                ExecuteProcess(
                    cmd=['ros2', 'daemon', 'start'],
                    name='daemon-start',
                    on_exit=[
                        OpaqueFunction(function=lambda context: ready_fn())
                    ],
                    additional_env={'RMW_IMPLEMENTATION': rmw_implementation}
                )
            ]
        )
    ])


class TestROS2TopicEchoPub(unittest.TestCase):

    @classmethod
    def setUpClass(cls, rmw_implementation):
        os.environ['RMW_IMPLEMENTATION'] = rmw_implementation
        cls.context = rclpy.context.Context()
        rclpy.init(context=cls.context)
        cls.node = rclpy.create_node(TEST_NODE, namespace=TEST_NAMESPACE, context=cls.context)
        cls.executor = SingleThreadedExecutor(context=cls.context)
        cls.executor.add_node(cls.node)

    @classmethod
    def tearDownClass(cls):
        cls.node.destroy_node()
        rclpy.shutdown(context=cls.context)

    @launch_testing.markers.retry_on_failure(times=5)
    def test_pub_basic(self, launch_service, proc_info, proc_output, rmw_implementation):
        params = [
            ('/clitest/topic/pub_basic', False, True),
            ('/clitest/topic/pub_compatible_qos', True, True),
            ('/clitest/topic/pub_incompatible_qos', True, False)
        ]
        for topic, provide_qos, compatible_qos in params:
            with self.subTest(topic=topic, provide_qos=provide_qos, compatible_qos=compatible_qos):
                # Check for inconsistent arguments
                assert provide_qos if not compatible_qos else True

                received_message_count = 0
                expected_minimum_message_count = 1
                expected_maximum_message_count = 5

                pub_extra_options = []
                subscription_qos_profile = 10
                if provide_qos:
                    if compatible_qos:
                        # For compatible test, put publisher at very high quality
                        # and subscription at low
                        pub_extra_options = [
                            '--qos-reliability', 'reliable',
                            '--qos-durability', 'transient_local']
                        subscription_qos_profile = QoSProfile(
                            depth=10,
                            reliability=ReliabilityPolicy.BEST_EFFORT,
                            durability=DurabilityPolicy.VOLATILE)
                    else:
                        # For an incompatible example, reverse the quality extremes
                        # and expect no messages to arrive
                        pub_extra_options = [
                            '--qos-reliability', 'best_effort',
                            '--qos-durability', 'volatile']
                        subscription_qos_profile = QoSProfile(
                            depth=10,
                            reliability=ReliabilityPolicy.RELIABLE,
                            durability=DurabilityPolicy.TRANSIENT_LOCAL)
                        expected_maximum_message_count = 0
                        expected_minimum_message_count = 0

                future = rclpy.task.Future()

                def message_callback(msg):
                    """If we receive one message, the test has succeeded."""
                    nonlocal received_message_count
                    received_message_count += 1
                    future.set_result(True)

                subscription = self.node.create_subscription(
                    String, topic, message_callback, subscription_qos_profile)
                assert subscription

                try:
                    command_action = ExecuteProcess(
                        cmd=(['ros2', 'topic', 'pub'] + pub_extra_options +
                             [topic, 'std_msgs/String', 'data: hello']),
                        additional_env={
                            'RMW_IMPLEMENTATION': rmw_implementation,
                            'PYTHONUNBUFFERED': '1'
                        },
                        output='screen'
                    )
                    with launch_testing.tools.launch_process(
                        launch_service, command_action, proc_info, proc_output,
                        output_filter=launch_testing_ros.tools.basic_output_filter(
                            filtered_rmw_implementation=rmw_implementation
                        )
                    ) as command:
                        self.executor.spin_until_future_complete(future, timeout_sec=10)
                    command.wait_for_shutdown(timeout=10)

                    # Check results
                    assert (
                        received_message_count >= expected_minimum_message_count and
                        received_message_count <= expected_maximum_message_count), \
                        'Received {} messages from pub, which is not in expected range {}-{}' \
                        .format(
                            received_message_count,
                            expected_minimum_message_count,
                            expected_maximum_message_count
                        )
                finally:
                    # Cleanup
                    self.node.destroy_subscription(subscription)

    @launch_testing.markers.retry_on_failure(times=5)
    def test_echo_basic(self, launch_service, proc_info, proc_output, rmw_implementation):
        params = [
            ('/clitest/topic/echo_basic', False, True),
            ('/clitest/topic/echo_compatible_qos', True, True),
            ('/clitest/topic/echo_incompatible_qos', True, False)
        ]
        for topic, provide_qos, compatible_qos in params:
            with self.subTest(topic=topic, provide_qos=provide_qos, compatible_qos=compatible_qos):
                # Check for inconsistent arguments
                assert provide_qos if not compatible_qos else True
                echo_extra_options = []
                publisher_qos_profile = 10
                if provide_qos:
                    if compatible_qos:
                        # For compatible test, put publisher at very high quality
                        # and subscription at low
                        echo_extra_options = [
                            '--qos-reliability', 'best_effort',
                            '--qos-durability', 'volatile']
                        publisher_qos_profile = QoSProfile(
                            depth=10,
                            reliability=ReliabilityPolicy.RELIABLE,
                            durability=DurabilityPolicy.TRANSIENT_LOCAL)
                    else:
                        # For an incompatible example, reverse the quality extremes
                        # and expect no messages to arrive
                        echo_extra_options = [
                            '--qos-reliability', 'reliable',
                            '--qos-durability', 'transient_local']
                        publisher_qos_profile = QoSProfile(
                            depth=10,
                            reliability=ReliabilityPolicy.BEST_EFFORT,
                            durability=DurabilityPolicy.VOLATILE)

                publisher = self.node.create_publisher(String, topic, publisher_qos_profile)
                assert publisher

                def publish_message():
                    publisher.publish(String(data='hello'))

                publish_timer = self.node.create_timer(0.5, publish_message)

                try:
                    command_action = ExecuteProcess(
                        cmd=(['ros2', 'topic', 'echo'] +
                             echo_extra_options +
                             [topic, 'std_msgs/String']),
                        additional_env={
                            'RMW_IMPLEMENTATION': rmw_implementation,
                            'PYTHONUNBUFFERED': '1'
                        },
                        output='screen'
                    )
                    with launch_testing.tools.launch_process(
                        launch_service, command_action, proc_info, proc_output,
                        output_filter=launch_testing_ros.tools.basic_output_filter(
                            filtered_rmw_implementation=rmw_implementation
                        )
                    ) as command:
                        # The future won't complete - we will hit the timeout
                        self.executor.spin_until_future_complete(
                            rclpy.task.Future(), timeout_sec=5
                        )
                    command.wait_for_shutdown(timeout=10)
                    # Check results
                    if compatible_qos:
                        assert command.output, 'Echo CLI printed no output'
                        assert 'data: hello' in command.output.splitlines(), (
                            'Echo CLI did not print expected message'
                        )
                    else:
                        assert not command.output, (
                            'Echo CLI should not have received anything with incompatible QoS'
                        )
                finally:
                    # Cleanup
                    self.node.destroy_timer(publish_timer)
                    self.node.destroy_publisher(publisher)