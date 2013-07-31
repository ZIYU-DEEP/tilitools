from cvxopt import matrix,spmatrix,sparse,mul
from cvxopt.blas import dot,dotu
from cvxopt.solvers import qp
import numpy as np
from kernel import Kernel  


class CssadMKL:
	"""Convex semi-supervised anomaly detection with multiple kernels with hinge loss and L2 regularizer
		as described in Goernitz et al., Towards Supervised Anomaly Detection, JAIR, 2013
	"""

	MSG_ERROR = -1	# (scalar) something went wrong
	MSG_OK = 0	# (scalar) everything alright

	PRECISION = 10**-5 # important: effects the threshold, support vectors and speed!

	X = [] 	# (matrix) our training data
	y = []	# (vector) corresponding labels (+1,-1 and 0 for unlabeled)
	cy = [] # (vector) converted label vector (+1 for pos and unlabeled, -1 for outliers)
	cl = [] # (vector) converted label vector (+1 for labeled examples, 0.0 for unlabeled)
	
	samples = -1 	# (scalar) amount of training data in X
	labeled = -1 	# (scalar) amount of labeled data
	dims = -1 	# (scalar) number of dimensions in input space

	cC = [] # (vector) converted upper bound box constraint for each example
	Cp = 1.0	# (scalar) the regularization constant for positively labeled samples > 0
	Cu = 1.0    # (scalar) the regularization constant for unlabeled samples > 0
	Cn = 1.0    # (scalar) the regularization constant for outliers > 0

	kappa = 1.0 # (scalar) regularizer for importance of the margin

	ktype = 'rbf' # (string) type of kernel to use
	kparam = [1.0]	# (scalar) additional parameter for the kernel

	isDualTrained = False	# (boolean) indicates if the oc-svm was trained in dual space

	alphas = []	# (vector) dual solution vector
	svs = []	# (vector) list of support vector (contains indices)

	threshold = matrix(0.0)	# (scalar) the optimized threshold (rho)

	kernel_ids = []

	mix = 1.0

	def __init__(self, X, y, kappa=1.0, Cp=1.0, Cu=1.0, Cn=1.0, ktype='mkl_rbf', param=[1.0]):
		self.X = X
		self.y = y
		self.kappa = kappa
		self.Cp = Cp
		self.Cu = Cu
		self.Cn = Cn
		self.ktype = ktype
		self.kparam = param
		(self.dims,self.samples) = X.size

		if (ktype=='mkl_rbf'):
			self.isMKL = True
			self.ktype = 'rbf'
			print('MKL RBF enabled')


		# these are counters for pos,neg and unlabeled examples
		npos = nunl = nneg = 0
		# these vectors are used in the dual optimization algorithm
		self.cy = matrix(1.0,(1,self.samples)) # cy=+1.0 (unlabeled,pos) & cy=-1.0 (neg)
		self.cl = matrix(1.0,(1,self.samples)) # cl=+1.0 (labeled) cl=0.0 (unlabeled)
		self.cC = matrix(Cp,(self.samples,1)) # cC=Cu (unlabeled) cC=Cp (pos) cC=Cn (neg)
		for i in range(self.samples):
			if y[0,i]==0:
				nunl += 1
				self.cl[0,i] = 0.0
				self.cC[i,0] = Cu
			if y[0,i]==-1:
				nneg += 1
				self.cy[0,i] = -1.0
				self.cC[i,0] = Cn
		npos = self.samples - nneg - nunl
		self.labeled = npos+nneg

		# if there are no labeled examples, then set kappa to 0.0 otherwise
		# the dual constraint kappa <= sum_{i \in labeled} alpha_i = 0.0 will
		# prohibit a solution
		if nunl==self.samples:
			print('There are no labeled examples hence, setting kappa=0.0')
			self.kappa = 0.0

		print('Creating new convex semi-supervised anomaly detection with {0}x{1} (dims x samples).'.format(self.dims,self.samples))
		print('There are {0} positive, {1} unlabeled and {2} outlier examples.'.format(npos,nunl,nneg))
		print('Kernel is {0} with parameter (if any) set to {1}'.format(ktype,param))


	def train_dual(self):
		# generate the base kernel matrix 
		self.kernel_ids = np.zeros((self.samples,), dtype=np.int)
		P = matrix(1.0, (self.samples, self.samples))

		t = self.mix

		selected = range(self.samples)
		for i in range(len(self.kparam)):
			# 1. get next kernel parameter and generate corresponding kernel
			par = self.kparam[i]
			nsel = len(selected)
			print('Current iteration {0}. Next parameter {1} for {2} examples..'.format(i,par,nsel))
			Q = Kernel.get_kernel(self.X, self.X, self.ktype, par)
			
			sigma = t
			if i==0: sigma = 1.0

			# 2. augment kernels
			for k in range(len(selected)):
				j = selected[k]
				P[j,:] = (1-sigma)*P[j,:] + sigma*Q[j,:]
				foo = P[j,j]
				P[:,j] = (1-sigma)*P[:,j] + sigma*Q[:,j]	
				P[j,j] = foo

			self.kernel_ids[selected] = i
			
			# train with current kernel
			self.train_dual_inner(P)
			# select examples
			selected = []
			(thres,MSG) = self.apply_dual(self.X)
			T = np.array(self.get_threshold())[0,0]
			for j in range(self.samples):
				#if (self.y[j]==+1 and thres[j]<T):
			#		selected.append(j)
				#if (self.y[j]==-1 and thres[j]>(T-CssadMKL.PRECISION)):
				if self.y[j]==-1:
					selected.append(j)


		print(self.kernel_ids[self.svs])
		print(self.kernel_ids)

		return CssadMKL.MSG_OK


	def train_dual_inner(self, P):
		"""Trains an one-class svm in dual with kernel."""
		if (self.samples<1 & self.dims<1):
			print('Invalid training data.')
			return CssadMKL.MSG_ERROR

		# number of training examples
		N = self.samples

		# generate the label kernel
		Y = self.cy.trans()*self.cy
		
		# generate the final PDS kernel
		P = mul(Y,P)

		# there is no linear part of the objective
		q = matrix(0.0, (N,1))
	
		# sum_i y_i alpha_i = A alpha = b = 1.0
		A = self.cy
		b = matrix(1.0, (1,1))

		#from matplotlib.pyplot import *
		#pcolor(np.array(P))
		#show()
		#print(b)
		(u,s,v) = np.linalg.svd(np.array(P)) 
		print(s)
		
		# inequality constraints: G alpha <= h
		# 1) alpha_i  <= C_i  
		# 2) -alpha_i <= 0
		# 3) kappa <= \sum_i labeled_i alpha_i  -> -cl' alpha <= -kappa
		G1 = spmatrix(1.0, range(N), range(N))
		G3 = -self.cl
		h1 = self.cC
		h2 = matrix(0.0, (N,1))
		h3 = -self.kappa
		
		G  = sparse([G1,-G1,G3])
		h  = matrix([h1,h2,h3])
		if (self.labeled==0):
			print('No labeled data found.')
			G  = sparse([G1,-G1])
			h  = matrix([h1,h2])

		# solve the quadratic programm
		sol = qp(P,-q,G,h,A,b,solver="mosek")


		# mark dual as solved
		self.isDualTrained = True

		# store solution
		self.alphas = sol['x']
		#print(self.alphas)

		# 1. find all support vectors, i.e. 0 < alpha_i <= C
		# 2. store all support vector with alpha_i < C in 'margins' 
		self.svs = []
		for i in range(N):
			if (self.alphas[i]>CssadMKL.PRECISION):
				self.svs.append(i)

		# these should sum to one
		print('Validate solution:')
		print('- found {0} support vectors'.format(len(self.svs)))
		
		summe = 0.0
		for i in range(N): summe += self.alphas[i]*self.cy[0,i]
		print('- sum_(i) alpha_i cy_i = {0} = 1.0'.format(summe))

		summe = 0.0
		for i in self.svs: summe += self.alphas[i]*self.cy[0,i]
		print('- sum_(i in sv) alpha_i cy_i = {0} ~ 1.0 (approx error)'.format(summe))
		
		summe = 0.0
		for i in range(N): summe += self.alphas[i]*self.cl[0,i]
		print('- sum_(i in labeled) alpha_i = {0} >= {1} = kappa'.format(summe,self.kappa))

		summe = 0.0
		for i in range(N): summe += self.alphas[i]*(1.0-self.cl[0,i])
		print('- sum_(i in unlabeled) alpha_i = {0}'.format(summe))
		summe = 0.0
		for i in range(N): 
			if (self.y[0,i]>=1.0): summe += self.alphas[i]
		print('- sum_(i in positives) alpha_i = {0}'.format(summe))
		summe = 0.0
		for i in range(N): 
			if (self.y[0,i]<=-1.0): summe += self.alphas[i]
		print('- sum_(i in negatives) alpha_i = {0}'.format(summe))

		# infer threshold (rho)
		self.calculate_threshold_dual()

		(thres, MSG) = self.apply_dual(self.X[:,self.svs])
		T = np.array(self.threshold)[0,0]
		cnt = 0
		for i in range(len(self.svs)):
			if thres[i,0]<(T-CssadMKL.PRECISION):
				cnt += 1
		print('Found {0} support vectors. {1} of them are outliers.'.format(len(self.svs),cnt))

		return CssadMKL.MSG_OK

	def calculate_threshold_dual(self):
		# 1. find all support vectors, i.e. 0 < alpha_i <= C
		# 2. store all support vector with alpha_i < C in 'margins' 
		margins = []
		for i in self.svs:
			if (self.alphas[i]<(self.cC[i,0]-CssadMKL.PRECISION)):
				margins.append(i)

		# 3. infer threshold from examples that have 0 < alpha_i < Cx
		# where labeled examples lie on the margin and 
		# unlabeled examples on the threshold
		(thres,MSG) = self.apply_dual(self.X[:,margins])

		idx = 0
		pos = neg = 0.0
		flag = flag_p = flag_n = False
		for i in margins:
			if (self.y[0,i]==0):
				# unlabeled examples with 0<alpha<Cu lie direct on the hyperplane
				# hence, it is sufficient to use a single example 
				self.threshold = thres[idx,0]
				flag = True
				break
			if (self.y[0,i]>=1):
				pos = thres[idx,0]
				flag_p = True
			if (self.y[0,i]<=-1):
				neg = thres[idx,0]
				flag_n = True
			idx += 1

		# check all possibilities (if no unlabeled examples with 0<alpha<Cu was found):
		# a) we have a positive and a negative, then the threshold is in the middle
		if (flag==False and flag_n==True and flag_p==True):
			self.threshold = 0.5*(pos+neg)
		# b) there is only a negative example, approx with looser threshold  
		if (flag==False and flag_n==True and flag_p==False):
			self.threshold = neg-CssadMKL.PRECISION
		# c) there is only a positive example, approx with tighter threshold
		if (flag==False and flag_n==False and flag_p==True):
			self.threshold = pos+CssadMKL.PRECISION

		# d) no pos,neg or unlabeled example with 0<alpha<Cx found :(
		if (flag==flag_p==flag_n==False):
			print('Poor you, guessing threshold...')
			(thres,MSG) = self.apply_dual(self.X[:,self.svs])
			self.threshold = 0.0

			idx = 0
			unl = pos = neg = neg2 = 0.0
			flag = flag_p = flag_n = False
			for i in self.svs:
				if (self.y[0,i]==0 and flag==False): 
					unl=thres[idx,0]
					flag=True
				if (self.y[0,i]==0 and thres[idx,0]>unl): unl=thres[idx,0]
				if (self.y[0,i]>=1 and flag_p==False): 
					pos=thres[idx,0]
					flag_p=True
				if (self.y[0,i]>=1 and thres[idx,0]>pos): pos=thres[idx,0]
				if (self.y[0,i]<=-1 and flag_n==False): 
					neg = neg2 =thres[idx,0]
					flag_n=True
				if (self.y[0,i]<=-1 and thres[idx,0]>neg): neg=thres[idx,0]
				if (self.y[0,i]<=-1 and thres[idx,0]<neg2): neg2=thres[idx,0]
				idx += 1

			# now, check the possibilities
			if (flag==True): 
				print('Threshold: unlabeled')
				self.threshold=unl
			if (flag_p==True and self.threshold<pos): 
				print('Threshold: positive {0}'.format(pos))
				self.threshold=pos
			if (flag_n==True and self.threshold<neg): 
				print('Threshold: negative {0}'.format(neg))
				self.threshold=neg
			if (flag_n == flag_p == True):
				self.threshold = 0.5*(pos + neg2)
				print('Threshold: middle {0}'.format(self.threshold))

		self.threshold = matrix(self.threshold)
		print('New threshold is {0}'.format(self.threshold))
		return CssadMKL.MSG_OK

	def get_threshold(self):
		return self.threshold

	def get_support_dual(self):
		return self.svs

	def apply_dual(self, Y):
		"""Application of a dual trained oc-svm."""
		# number of support vectors
		N = len(self.svs)
		(Nd,Ny) = Y.size

		# check number and dims of test data
		(tdims,tN) = Y.size
		if (self.dims!=tdims or tN<1):
			print('Invalid test data')
			return 0, CssadMKL.MSG_ERROR

		if (self.isDualTrained!=True):
			print('First train, then test.')
			return 0, CssadMKL.MSG_ERROR

		# generate a kernel matrix
		#P = Kernel.get_kernel(Y, self.X[:,self.svs], self.ktype, self.kparam[0])

		t = self.mix
		P = matrix(1.0, (Ny,N))
		for i in range(len(self.kparam)):
			par = self.kparam[i]
			sigma = t
			if i==0: sigma = 1.0
			print('Current iteration {0}. Next parameter {1}..'.format(i,par))
			Q = Kernel.get_kernel(Y, self.X[:,self.svs], self.ktype, par)
			for j in range(N):
				if (self.kernel_ids[self.svs[j]]>=i):
					P[:,j] = (1-sigma)*P[:,j] + sigma*Q[:,j]


		# apply trained classifier
		prod = matrix([self.alphas[i,0]*self.cy[0,i] for i in self.svs],(N,1))
		res = matrix([dotu(P[i,:],prod) for i in range(tN)]) 
		return res, CssadMKL.MSG_OK