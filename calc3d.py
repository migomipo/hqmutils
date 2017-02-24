# Copyright © 2016-2017, John Eriksson
# https://github.com/migomipo/hqmutils
# See LICENSE for terms of use

import math


class Vector3D():

    def __init__(self, x,y,z):
        self._data = (x,y,z)
        
    def __getitem__(self,i):
        return self._data[i]  
    
    def __add__(self, a):       
        return Vector3D(
            self[0]+a[0], 
            self[1]+a[1], 
            self[2]+a[2])
            
    def __sub__(self, a):       
        return Vector3D(
            self[0]-a[0], 
            self[1]-a[1], 
            self[2]-a[2])
            
    def __rmul__(self, a):
        return Vector3D(
            a*self[0], 
            a*self[1], 
            a*self[2])      
        
            
    def length(self):       
        return math.sqrt(self.dot(self))                   
            
    def dot(self, a):
        return (self[0]*a[0]+ 
                self[1]*a[1]+ 
                self[2]*a[2])
                
    def cross(self, a):
        return Vector3D(
            self[1]*a[2]-self[2]*a[1], 
            self[2]*a[0]-self[0]*a[2], 
            self[0]*a[1]-self[1]*a[0])
                
    def normal(self):
        length = self.length()
        if length==0:
            return Vector3D(0,0,0)
        return (1/length)*self
            
    def __str__(self):
        return str(self._data)
        
    def __repr__(self):
        return "Vector3D" + str(self._data)

class Matrix3D():

    def __init__(self, r1, r2, r3):
        self._data = (tuple(r1[:3]), tuple(r2[:3]), tuple(r3[:3]))
        
    def __mul__(self, a):
        res = [[0,0,0],[0,0,0],[0,0,0]]
        for i in range(3):
            for j in range(3):
                for k in range(3):
                    res[i][j] += self[(i,k)]*a[(k,j)]
                
        return Matrix3D(*res)
        
    @classmethod
    def from_rows(cls, r1, r2, r3):
        l = ((r[0], r[1], r[2]) for r in [r1, r2, r3])
        return cls(*l)
        
    @classmethod
    def from_columns(cls, c1, c2, c3):
        l = ((c1[i], c2[i], c3[i]) for i in range(3))
        return cls(*l)
        
    def __getitem__(self, arg):
        r,c = arg
        return self._data[r][c]
           
    def get_column_vectors(self):
        return (
            Vector3D(self[(0,0)], self[(1,0)], self[(2,0)]),
            Vector3D(self[(0,1)], self[(1,1)], self[(2,1)]),
            Vector3D(self[(0,2)], self[(1,2)], self[(2,2)])
        )
      
    def get_row_vectors(self):
        return (
            Vector3D(self[(0,0)], self[(0,1)], self[(0,2)]),
            Vector3D(self[(1,0)], self[(1,1)], self[(1,2)]),
            Vector3D(self[(2,0)], self[(2,1)], self[(2,2)])
        )

    def __str__(self):
        nums = []
        for i in range(3):
            nums.append(self[(i,0)]) 
            nums.append(self[(i,1)]) 
            nums.append(self[(i,2)])
    
        return ("[{:+f} {:+f} {:+f}\n"
                " {:+f} {:+f} {:+f}\n"
                " {:+f} {:+f} {:+f}]\n").format(*nums)