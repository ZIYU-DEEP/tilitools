from cvxopt import matrix,spmatrix,sparse
from cvxopt.blas import dotu
from cvxopt.solvers import qp
import numpy as np

class OCSVM:
    """One-class support vector machine

        'Estimating the support of a high-dimensional distribution.',
        Sch\"{o}lkopf, B and Platt, J C and Shawe-Taylor, J and Smola, a J and Williamson, R C,
        Microsoft, 1999

    """
    PRECISION = 10**-3 # important: effects the threshold, support vectors and speed!

    kernel = None 	# (matrix) our training kernel
    samples = -1 	# (scalar) amount of training data in X
    C = 1.0	 # (scalar) the regularization constant > 0

    alphas = None  # (vector) dual solution vector
    svs = None  # (vector) support vector indices
    threshold = 0.0	 # (scalar) the optimized threshold (rho)

    def __init__(self, kernel, C=1.0):
        self.kernel = kernel
        self.C = C
        (self.samples,foo) = kernel.size
        print('Creating new one-class svm with {0} samples and C={1}.'.format(self.samples,C))

    def fit(self):
        """Trains an one-class svm in dual with kernel."""
        if (self.samples<1):
            print('Invalid training data.')
            return

        # number of training examples
        N = self.samples

        # generate a kernel matrix
        P = self.kernel
        # there is no linear part of the objective
        q = matrix(0.0, (N,1))

        # sum_i alpha_i = A alpha = b = 1.0
        A = matrix(1.0, (1,N))
        b = matrix(1.0, (1,1))

        # 0 <= alpha_i <= h = C
        G1 = spmatrix(1.0, range(N), range(N))
        G = sparse([G1,-G1])
        h1 = matrix(self.C, (N,1))
        h2 = matrix(0.0, (N,1))
        h = matrix([h1,h2])
        sol = qp(P,-q,G,h,A,b)

        # store solution
        self.alphas = sol['x']

        # find support vectors
        self.svs = []
        for i in range(N):
            if self.alphas[i]>OCSVM.PRECISION:
                self.svs.append(i)

        thres = self.apply_dual(self.kernel[self.svs,self.svs])
        self.threshold = matrix(max(thres))

        T = np.single(self.threshold)
        cnt = 0
        for i in range(len(self.svs)):
            if thres[i,0] < (T-OCSVM.PRECISION):
                cnt += 1

        #print(self.alphas)
        print('Found {0} support vectors. {1} of them are outliers.'.format(len(self.svs),cnt))
        print('Threshold is {0}'.format(self.threshold))


    def get_threshold(self):
        return self.threshold

    def get_support_dual(self):
        return self.svs

    def get_alphas(self):
        return self.alphas

    def get_support_dual_values(self):
        return self.alphas[self.svs]

    def set_train_kernel(self,kernel):
        (dim1,dim2) = kernel.size
        if (dim1!=dim2 and dim1!=self.samples):
            print('(Kernel) Wrong format.')
            return
        self.kernel = kernel;

    def apply_dual(self, kernel):
        """Application of a dual trained oc-svm."""
        # check number and dims of test data
        tN, foo = kernel.shape
        if tN < 1:
            print('Invalid test data')
            return -1
        # apply trained classifier
        res = matrix([dotu(kernel[i,:],self.alphas[self.svs]) for i in range(tN)])
        return res
