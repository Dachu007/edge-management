# AI-Augmented Edge Resource Management for Smart Cities

An intelligent edge resource management system that uses Q-learning-based task allocation to distribute smart-city workloads across multiple edge nodes. The system monitors node resources, evaluates task requirements, balances workloads, and compares allocation policies to support efficient task execution with reduced latency and energy consumption.

# About

AI-Augmented Edge Resource Management for Smart Cities is a Python-based project designed to improve resource allocation in smart-city edge computing environments.Smart-city applications such as traffic monitoring, surveillance systems, emergency services, and environmental monitoring generate different types of workloads. When multiple applications request computing resources simultaneously, some edge servers may become overloaded while other servers remain underutilized.This can increase processing delays, resource wastage, and energy consumption.This project addresses these challenges through an intelligent resource management approach. It simulates multiple edge nodes and uses a Q-learning-based reinforcement learning agent to select suitable nodes for incoming tasks based on their resource availability, workload, latency, deadline requirements, and energy estimates.The application also provides a web-based dashboard to monitor edge-node conditions, submit tasks, compare allocation policies, train the AI agent, and analyze system performance.

# Features

1. AI-Based Task Allocation: Uses a Q-learning reinforcement learning agent to make intelligent edge-node selection decisions.

2. Resource Monitoring: Monitors CPU utilization, memory, workload, queue length, latency, and power consumption.

3. Workload Balancing: Identifies overloaded nodes and supports better distribution of incoming tasks.

4. Multiple Allocation Policies: Compares the AI-based policy with four baseline allocation policies.

5. Live Dashboard: Displays edge-node status, resource utilization, charts, recent decisions, and system events.

6. Task Submission: Supports traffic, surveillance, emergency, and environmental monitoring workloads.

7. AI Agent Training: Allows the Q-learning agent to be trained and stores its Q-table.

8. Performance Analysis: Evaluates task completion time, deadline success, energy estimates, and resource utilization.

9. Test Case Execution: Includes seven test cases (TC01–TC07) to check system behavior.

 10. Decision Logging: Maintains records of task allocation decisions and performance results.

# Requirements

1.Operating System: Windows 10/11, Ubuntu, or another compatible operating system.

2.Programming Language: Python 3.9 or later.

3.Framework: Flask 2.3 or later.

4.Frontend Technologies: HTML, CSS, and JavaScript.

5.Visualization: Chart.js for dashboard charts.

6.AI Technique: Q-learning (Reinforcement Learning).

7.Development Environment: Visual Studio Code (VS Code)and IDE.

8.Version Control: Git and GitHub.

9.Additional Dependencies: Python packages listed in requirements.txt

# System Architecture

The system follows a feedback-based resource management architecture. Incoming smart-city tasks are evaluated against the current resource conditions of available edge nodes. The AI allocator selects a suitable node, while the monitoring and reporting modules track execution performance.

<img width="623" height="326" alt="image" src="https://github.com/user-attachments/assets/55481d11-6c15-4645-8484-92fa180c3b5f" />

```
edge-resource-manager/
├── app.py                  
├── edge/
│   ├── models.py           
│   ├── monitor.py         
│   ├── allocator.py        
│   ├── balancer.py        
│   ├── reporter.py        
│   ├── simulation.py       
│   └── testcases.py       
├── templates/index.html    
├── static/css/style.css
├── static/js/app.js        
├── static/js/chart.umd.min.js  
├── models/q_table.json     
├── tests/test_system.py    
└── requirements.txt
```

# Output

# Output 1 – Live Dashboard

<img width="1535" height="828" alt="Screenshot 2026-11-24 175734" src="https://github.com/user-attachments/assets/db7101aa-d34f-45de-b7da-736f76bfc533" />

# Output 2 – Task Submission

<img width="1535" height="836" alt="Screenshot 2026-11-24 175858" src="https://github.com/user-attachments/assets/4ae38fe4-7929-4fcf-b2ff-69697a5f03cb" />

# Output 3 – Policy Comparison

<img width="1535" height="832" alt="Screenshot 2026-11-24 175832" src="https://github.com/user-attachments/assets/fa42ea5d-088d-48e7-997a-2902b8f2c70c" />

# Output 4 – AI Agent Training

<img width="1535" height="835" alt="Screenshot 2026-11-24 175945" src="https://github.com/user-attachments/assets/f1ee54cb-c8db-471a-926c-9055dd8c2a25" />

# Output 5 – Test Cases

<img width="1535" height="831" alt="Screenshot 2026-11-24 180153" src="https://github.com/user-attachments/assets/163d3349-285d-48dc-81a9-ebfa088f9fd9" />

# Output 6 – Decision Log

<img width="1535" height="831" alt="Screenshot 2026-11-24 175933" src="https://github.com/user-attachments/assets/0ef95da6-a129-47cb-afd1-942d9825f392" />

# Result and Impact

The project demonstrates an approach to efficient resource allocation in smart-city edge computing. It analyzes CPU, memory, bandwidth, queue length, and latency across four edge nodes.

The results help identify overloaded nodes, improve workload distribution, and support better task allocation. The system aims to reduce latency and energy consumption through efficient resource management.

# Articles published / References

1. M. Satyanarayanan, "The Emergence of Edge Computing," IEEE Computer, vol. 50, no. 1, pp. 30–39, 2017. DOI: 10.1109/MC.2017.9.

2. W. Shi, J. Cao, Q. Zhang, Y. Li, and L. Xu, "Edge Computing: Vision and Challenges," IEEE Internet of Things Journal, vol. 3, no. 5, pp. 637–646, 2016. DOI: 10.1109/JIOT.2016.2579198.

3. Y. Mao, C. You, J. Zhang, K. Huang, and K. B. Letaief, "A Survey on Mobile Edge Computing: The Communication Perspective," IEEE Communications Surveys & Tutorials, vol. 19, no. 4, pp. 2322–2358, 2017. DOI: 10.1109/COMST.2017.2745201.
