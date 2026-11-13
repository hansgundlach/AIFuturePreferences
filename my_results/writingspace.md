
Do you thinnk any of these are patentable or I shouldn't publish for patent reasons. 
Go over with claude publishing things 

On the Verge of MetaTraining

A few months ago I investigated whether LLMs could do weight based programming (I’ve uploaded this work here). My tests on GPT 5.4 failed so I  put the project on pause. The last week we saw that this is no longer the case, at least for some tasks. In Sparks of Weight-Space Programming, Takehi et al. showed that GPT-6 Astra could read and write neural network weights directly, including writing small networks from scratch and improving a Qwen model through targeted weight modifications.  I don’t know the true validity of these results but I’ve suspected for a while that something like this would eventually be possible. There has also been very similar work on this for much longer than the last 10 years, going back to Jürgen Schmidhuber’s work on fast-weight programmers in the early 1990s. His approach involved one neural network learning to modify the weights of another. Others developed similar ideas, including Ha et al. (2016), HyperNetworks, which used neural networks to generate the weights of other networks, and Ba et al. (2016), Using Fast Weights to Attend to the Recent Past, which investigated rapidly changing weights as a form of memory.  However, with the better power and efficiency of modern LLMs I think these methods will become more important. We may see many of these research paths restarting as well as new research areas emerging. I want to highlight a few directions that seem interesting below as well as . Here I wan't to highlight metatraining more as AIs being involved in the process of training or as replacemnet for training rather than simply LLMs designign training procedures. Here are some trends that I want to identify. 
I'd like ot investigate some of these myself but I suspect labs maybe implementing some if not all of these. 




Capability Implications (Somewhat technical) 

MidTerm 
- Runtime weight adjustment, ie change the weights depending on task. This is simply an application of weight based programming but I want to mention its greater potential in this area. Neural networks could potentially upload changes to their weights for certain long form tasks (for instance completion a benchmark)  then delete these memories when the task is complete (think of Neo downloading kong-fu in the matrix). 



Anyone who trains neural networks knows that 
Optimizer entirely determined by neural network ie step size, gradient direction, or other parameters in optimization determined by neural network rather than an optimizer algorithm like Adam. 





Why 
- network architecture and algorithms being modified on the fly/dynamically during the training, there is no reason that weights are the only thing that should change during training. For instance, much of current llm training uses fixed algorithms with fixed hyper parameter and simple hyperparameter schedules during training. None of these things have to be fixed.  Architecture , scafolding, hyperparameters  could also be modified during training at the same time as weights. Trainign space will become much more deep and dynamics. One could also dynamically change training algorithms on the fly. For instance, using Adam for one training environment or designing custom training algorithms for a given data or training regime (maybe this could be called algorithmic curricula training). 





*Simulated training.
 Training is a process somewhat similar to other natural processes we simulate, for instance thermal annealing or diffusion. If LLMs can learn to simulate these processes, naturally they may also be able to simulate the training process. Given initial weights and training data, the model would output the final weights that would have occurred via gradient descent, without executing all the intermediate optimization steps. There is already related work on generating neural network parameters, including HyperDiffusion (2023) and Neural Network Diffusion (2024). Even closer to this idea, Predictive Differential Training (ICLR 2026) predicts future network weights using learned training dynamics to bypass some gradient descent iterations. In the future, this might lead to simulating entire training runs. 
 
*Training Data Level Programming:
Just as weight programming can convert code to its weight-based version, LLMs may be able to predict what weight changes will occur due to training data. They could then program the training data to insert specific weight changes or programs into the trained LLM. This is closely connected to influence functions and data poisoning. In particular, Infusion (2026) explicitly studies the reverse of training-data attribution: modifying training examples to induce desired changes in model behavior through their effects on parameters. I suspect sufficiently capable LLMs will be able to perform something like this much more generally, for instance being able to program certain types of subliminal learning. 

*Dynamic data and environment modification during the training proces
This is already a very active area of interest so I will keep the description broad. I think more advanced forms of curricula learingin and self-adjusting RL environments will become more imporatnt. 

Run-Time and Eval MetaLearning 
* Meta-evals, i.e., given weights, determine what an eval score would be if the LLM had been run on this eval. This has already been investigated for smaller networks. Predicting Neural Network Accuracy from Weights (2020) demonstrated that a network's accuracy could be predicted surprisingly well from its weights alone, without evaluating it on input data. 



- Meta-evals, ie given weights determine what eval score would be if the LLM had been run on this eval 
- Be able to predict inputs from outputs of neural network 
- Predetermine what the model loss and evaluation scores would be based on training compute, training data, and evaluation environments (basically black box scaling laws). 

Long Term Transpile betweeen Intelligence
In the long term, I’m suspicious that neural networks would be the most efficient way to implement programs. We may be able to compile intelligence to whatever form is most efficient. Neurla networks may 
 in fact be the most efficient way to implement intelligence because of our hardware optimization  for matrix multiplication. On the other hand,  superintelligence may be much more eafificnet in designing fast custom hardware for whatever implementation program is preferred. 



- Non neural network can be compiled and decompield to code. Code is less memory efficient but more interpretable and possibly faster to execute. 


Governance and Safety Implications: 

1. AI verification and Space Training: 
I think metatraining, and metra-programming have a number of important implications for AI safety. First, as many online have shown this is another direction for RSI. I think inference time monitoring will become increasingly. Most, AI pause programs are focused around monitoring trainign and bakpropagations. I suspect modles will increasingly be able to self improve with inference alone either via weight programming, training simulation, scaffolding improvements, self architecture changes, etc. Therefore, we need to have verification protocols that are robust to inference time improvements. I think we might also see training become much more flexible. Currently backpropagation focused training involves large amounts of synchronous communication ie sending weights and gradient updates between GPUs. This means trainign has to be fairly centralized. However, weight programming, scaffolding improvements, algorithmic improvements etc can be More easily communicated and could be done less scynchonously then current training. This would allow serious llm training to take place in space where latency and bandwidth are an issue between GPU sattelites. It could also allow much more distributed training on earth allowing groups to train in many more locations rather than in one centralized data centers. This may pose additional training monitorability concerns. I suspect compute will still be important and we may see even more “scale dependent” change as before as now compute is necessary to manage the training process. In addition, many of the custom algorithmic modifications look much more beneficial for large training runs that have a much larger diversity of training environments. 

These developments also have key safety implications. AIs will have key ability to understand their training. They will be able to see how certain data modifies themselves and how to modify the training process to preserve the goals they are making. This is already an issue in RL training which occurs in alignment faking. Even if models are making weight modification that are able to improve themselves how can we trust the modifications they make, are they not adding secret capabilities ontop of mundane benchmark improvements? The prospect of weight level programming introduce the meta interpretability problem of understanding the weight level programmer and their programming. 

Further, data level programming, will allow models to covertly influence themselves and other models in ways that were not possible before. For instance, by changing the training data to covertly modify themselves to be less controlable or be able to emergently misalign/covertly finetune other models with arbitrary goals. I'm excited to run experiments to determine this. 

================

Junk : 



- Program neural training data programming, as weight programming can convert code to its weight based version, LLMs will be able to predict what weight changes will occur due to training data they will then be able to program the training data to insert specific weight or specific programs into the trained LLM.



- Dynamic data and environment modification during training process, for instance changing difficulty of RL environment, advanced curricula learning and other methods will become more common. This is already been significantly studied see here (——). 

I’m put some of the work that is still novel in the appendix in light of the twitter stream. I don’t think weight space programming will replace regular training in the near to mid term, but I think there wil certainly be a lot of significant hybrid developments in the near future. I’ve listed some of the hybrid developments I suspect to happen soon. As well as some results from my metraining investigation. I think many of these are currently possible but outside of my token budget (I’m actually between jobs rn more about this soon). I also think the labs are currently implementing some if not all of these. 


 These are not yet general simulations of arbitrary large training runs, but I think this is a direction worth investigating.


There has also been very simliiar work on this at least for the last 10 years back to Jurgen Schmidhubers work in 2016. There are others that had the same idea at the time as well including : ——. ———.  Metatraining was a more popular approach before the rise of LLMs.


Trainng Simulation: 
Training is a process with similar to other natural processes we simulate. For instance, thermal annealing or diffusion. LLMs have been used to simulate these processes and naturally LLMs will be able to simulate the training process. Simulated training, given initial weights and training data output the final weights that would have occurred via gradient descent 


 Yet, I think such algorithmic gains will not net out in useful capabilities (see another post). 





====================
Appendix Examples of These Abilites:

AIs being able to reason about their training is an important part of metatrainig. Here I ask AIs to predict the weights of a small neural network after gradient descent. From a capability perspective, this might allow models to skip gradient descent when needed or substitute thinking for backpropagation. There might be key simplifications that allow us to simulate rather then run gradient descent or other training methods.  However, I doubt that it could be in general faster without breakthroughs in understanding of gradient descent. I think it is also helps us understand model’s ability to understand their own training process (although it is quite a high bar). It also helps us understand how well models understand the gradient compliation process which is a key ability if modles want to do data level 


Most of this is AI generated but might be of value to other researchers. 

Example: Predicting the Weights After Gradient Descent: 
Models do noticeably better than chance. I don’t think this is yet a superhuman capability but modles can use published models of gradient descent to model the outcome of training. 


- Predict weights after training 

Gradient training is mathematical process that can be predicted just like any other physical process. 

- Predict input that lead to output 


Metaprogramming Era:


- Weight prediction 
- Predict input based on output of neural network 
- 



I’ve been experiment with 






However, now that it is in the news and widely discussed I think it is time to discuss the impacts and 

