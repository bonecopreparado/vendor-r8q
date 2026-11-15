# P1r4 scheduler boot correction

The submitted persistent kernel log contains two Oops reports on the compiled
4.19.325-r8q-nflog-staging1 kernel, both at select_task_rq_fair+0x15dc.
This is a device failure of P1r3; passing compilation and image readback did not
prove boot. The raw logs are private and are not included here.

The source changed fits_capacity to accept a CPU number and read that CPU runqueue
threshold. select_cpu_candidates still passed capacity_of(cpu) as its second
argument, using capacity values such as 512/1024 as CPU indexes. The recorded
load instruction reads offset 0xad0 from the computed runqueue; the recorded
base plus this offset reproduces the fault address exactly.

The correction passes cpu, preserving the actual threshold provider, uclamp,
affinity and candidate selection. test_capacity.py compiles the actual source
functions, with bounded 8-CPU queues and distinct 512/1024 capacities. The
original code aborts the bounds assertion; corrected code passes selection,
uclamp saturation, latency-sensitive idle choice and restricted-affinity cases.
The fixture does not emulate a full kernel or establish hardware boot success.

SUSFS remains enabled. Full compile, binary verification and complete image
reconstruction must pass before distributing P1r4; hardware boot still needs
a new device test. Userdata and metadata are not modified by this correction.
The recovery mapping/Format Data error is separate: userdata is mapped through
dm-5 and the latest recovery inventory shows a successful F2FS mount at /data.
No forced mkfs, crypto-key deletion or blind mapping removal is prescribed.
